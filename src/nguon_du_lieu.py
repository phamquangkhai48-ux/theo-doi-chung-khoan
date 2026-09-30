"""
Lấy dữ liệu từ các nguồn: vnstock (cổ phiếu VN, BCTC), yfinance (chỉ số thế giới),
TradingView / FRED (lợi suất trái phiếu), Vietcombank (tỷ giá), SJC (giá vàng).

Nguyên tắc: mỗi hàm tự thử nhiều cách, lỗi ở một nguồn KHÔNG làm dừng chương trình.
Thư viện vnstock thay đổi cú pháp giữa các phiên bản, nên mỗi hàm thử lần lượt
cú pháp mới (v4) rồi đến cú pháp cũ (v3).
"""
from __future__ import annotations

import io
import logging
import os
import re
import time
import unicodedata
from datetime import date, timedelta

import pandas as pd
import requests

log = logging.getLogger("du_lieu")
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"}

NGHI_GIAY = 3.2          # sẽ được main.py ghi đè theo config
_lan_goi_cuoi = 0.0


def nghi():
    """Giãn cách các lần gọi vnstock để không vượt giới hạn (khách: ~20 lần/phút)."""
    global _lan_goi_cuoi
    cho = NGHI_GIAY - (time.time() - _lan_goi_cuoi)
    if cho > 0:
        time.sleep(cho)
    _lan_goi_cuoi = time.time()


def bo_dau(s) -> str:
    """'Lợi nhuận sau thuế' -> 'loi nhuan sau thue' (để so khớp tên cột)."""
    s = str(s).replace("đ", "d").replace("Đ", "D")
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", s.lower()).strip()


def _dang_nhap_vnstock():
    """Nếu có API key (GitHub Secret VNSTOCK_API_KEY) thì dùng để tăng giới hạn."""
    key = os.environ.get("VNSTOCK_API_KEY", "").strip()
    if not key:
        return
    for ten_ham in ("change_api_key", "register_user"):
        try:
            import vnstock
            ham = getattr(vnstock, ten_ham, None)
            if ham:
                ham(key) if ten_ham == "change_api_key" else ham(api_key=key)
                log.info("Đã dùng API key vnstock")
                return
        except Exception as e:  # noqa: BLE001
            log.debug("Không dùng được API key qua %s: %s", ten_ham, e)


_dang_nhap_vnstock()


# ======================================================================
# DANH SÁCH VN30
# ======================================================================
def _lay_ma_tu_bang(obj) -> list[str]:
    if obj is None:
        return []
    if isinstance(obj, pd.Series):
        vals = obj.tolist()
    elif isinstance(obj, pd.DataFrame):
        cot = next((c for c in obj.columns if bo_dau(c) in ("symbol", "ticker", "ma", "code")), obj.columns[0])
        vals = obj[cot].tolist()
    else:
        vals = list(obj)
    return [str(v).strip().upper() for v in vals if re.fullmatch(r"[A-Za-z0-9]{3}", str(v).strip())]


def lay_danh_sach_vn30() -> list[str]:
    cach_thu = []

    def v4():
        from vnstock import Reference
        return Reference().equity.list_by_group(group="VN30")

    def v3():
        from vnstock import Listing
        return Listing().symbols_by_group("VN30")

    def v3_cu():
        from vnstock import Vnstock
        return Vnstock().stock(symbol="ACB", source="VCI").listing.symbols_by_group("VN30")

    cach_thu = [v4, v3, v3_cu]
    for ham in cach_thu:
        try:
            nghi()
            ma = _lay_ma_tu_bang(ham())
            if 25 <= len(ma) <= 35:
                return sorted(set(ma))
        except Exception as e:  # noqa: BLE001
            log.debug("Lấy VN30 bằng %s lỗi: %s", ham.__name__, e)
    return []


# ======================================================================
# GIÁ CỔ PHIẾU VIỆT NAM
# ======================================================================
def chuan_hoa_gia(df: pd.DataFrame) -> pd.DataFrame | None:
    """Đưa về dạng: index = ngày, cột open/high/low/close/volume; giá theo NGHÌN đồng."""
    if df is None or len(df) == 0:
        return None
    df = df.copy()
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [c[0] for c in df.columns]
    df.columns = [bo_dau(c) for c in df.columns]
    doi_ten = {"date": "time", "tradingdate": "time", "trading_date": "time", "ngay": "time",
               "datetime": "time"}
    df = df.rename(columns=doi_ten)
    if "time" not in df.columns:
        df = df.reset_index()
        df.columns = [bo_dau(c) for c in df.columns]
        df = df.rename(columns={"index": "time", **doi_ten})
    can = ["time", "open", "high", "low", "close", "volume"]
    if not all(c in df.columns for c in can):
        return None
    df = df[can].copy()
    df["time"] = pd.to_datetime(df["time"], errors="coerce")
    if getattr(df["time"].dt, "tz", None) is not None:
        df["time"] = df["time"].dt.tz_localize(None)
    df = df.dropna(subset=["time", "close"]).sort_values("time").drop_duplicates("time", keep="last")
    df = df.set_index("time")
    for c in can[1:]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    # Một số nguồn trả giá theo đồng (105000), một số theo nghìn đồng (105.0)
    if df["close"].median() > 1000:
        for c in ["open", "high", "low", "close"]:
            df[c] = df[c] / 1000
    return df


def lay_gia_co_phieu(ma: str, so_ngay: int = 420) -> tuple[pd.DataFrame | None, str]:
    """Trả về (bảng giá, tên nguồn)."""
    bat_dau = (date.today() - timedelta(days=so_ngay)).isoformat()
    ket_thuc = date.today().isoformat()

    def v4():
        from vnstock import Market
        return Market().equity.ohlcv(symbol=ma, start=bat_dau, end=ket_thuc)

    def v3():
        from vnstock import Vnstock
        return Vnstock().stock(symbol=ma, source="VCI").quote.history(start=bat_dau, end=ket_thuc, interval="1D")

    def v3_quote():
        from vnstock import Quote
        return Quote(symbol=ma, source="VCI").history(start=bat_dau, end=ket_thuc, interval="1D")

    for ten, ham in (("vnstock", v4), ("vnstock", v3), ("vnstock", v3_quote)):
        try:
            nghi()
            df = chuan_hoa_gia(ham())
            if df is not None and len(df) >= 30:
                return df, ten
        except Exception as e:  # noqa: BLE001
            log.debug("%s: %s lỗi: %s", ma, ham.__name__, e)

    # Dự phòng: Yahoo Finance (mã .VN)
    try:
        import yfinance as yf
        df = yf.download(f"{ma}.VN", start=bat_dau, progress=False, auto_adjust=False, threads=False)
        df = chuan_hoa_gia(df)
        if df is not None and len(df) >= 30:
            return df, "yahoo"
    except Exception as e:  # noqa: BLE001
        log.debug("%s: yahoo lỗi: %s", ma, e)
    return None, ""


# ======================================================================
# BÁO CÁO TÀI CHÍNH
# ======================================================================
def _goi_bctc(ma: str, loai: str):
    """loai: 'income' hoặc 'ratio'. Trả về DataFrame thô."""
    def v4():
        from vnstock import Fundamental
        eq = Fundamental().equity
        if loai == "income":
            return eq.income_statement(symbol=ma, period="quarter")
        return eq.ratios(symbol=ma, period="quarter")

    def v3():
        from vnstock import Vnstock
        fin = Vnstock().stock(symbol=ma, source="VCI").finance
        if loai == "income":
            return fin.income_statement(period="quarter", lang="vi", dropna=True)
        return fin.ratio(period="quarter", lang="vi", dropna=True)

    def v3_finance():
        from vnstock import Finance
        fin = Finance(symbol=ma, source="VCI")
        if loai == "income":
            return fin.income_statement(period="quarter", lang="vi")
        return fin.ratio(period="quarter", lang="vi")

    loi = []
    for ham in (v4, v3, v3_finance):
        try:
            nghi()
            df = ham()
            if df is not None and len(df) > 0:
                return df
        except Exception as e:  # noqa: BLE001
            loi.append(f"{ham.__name__}: {e}")
    log.debug("%s: không lấy được %s: %s", ma, loai, " | ".join(loi))
    return None


_KY_QUY = [
    re.compile(r"(?P<y>20\d{2})\s*[-_/ ]?\s*q(?P<q>[1-4])", re.I),
    re.compile(r"q(?P<q>[1-4])\s*[-_/ ]?\s*(?P<y>20\d{2})", re.I),
    re.compile(r"quy\s*(?P<q>[1-4])\D+(?P<y>20\d{2})", re.I),
]


def _doc_ky(s) -> tuple[int, int] | None:
    t = bo_dau(s)
    for p in _KY_QUY:
        m = p.search(t)
        if m:
            return int(m.group("y")), int(m.group("q"))
    return None


def chuan_hoa_bctc(df: pd.DataFrame | None) -> pd.DataFrame | None:
    """
    Đưa bảng BCTC về dạng: mỗi dòng là một quý, index = (năm, quý),
    tên cột đã bỏ dấu, chữ thường. Hỗ trợ cả bảng "dọc" và "ngang".
    """
    if df is None or len(df) == 0:
        return None
    df = df.copy()
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [" ".join(str(x) for x in c if str(x) != "" and "unnamed" not in str(x).lower())
                      for c in df.columns]

    # Trường hợp 1: các cột là các quý (bảng ngang) -> xoay lại
    cot_ky = [c for c in df.columns if _doc_ky(c)]
    if len(cot_ky) >= 4:
        cot_ten = next((c for c in df.columns if c not in cot_ky
                        and not pd.api.types.is_numeric_dtype(df[c])), None)
        if cot_ten is not None:
            df = df.set_index(cot_ten)
        df = df[cot_ky].T
        df.index = pd.MultiIndex.from_tuples([_doc_ky(c) for c in df.index], names=["nam", "quy"])
        df.columns = [bo_dau(c) for c in df.columns]
    else:
        # Trường hợp 2: mỗi dòng là một quý
        df.columns = [bo_dau(c) for c in df.columns]
        if df.index.name or not isinstance(df.index, pd.RangeIndex):
            df = df.reset_index()
            df.columns = [bo_dau(c) for c in df.columns]
        cot_nam = next((c for c in df.columns if c in ("yearreport", "year", "nam", "year report")
                        or c.endswith(" nam") or c.endswith("yearreport")), None)
        cot_quy = next((c for c in df.columns if c in ("lengthreport", "quarter", "quy", "ky", "length report")
                        or c.endswith(" ky") or c.endswith("lengthreport") or c.endswith(" quy")), None)
        if cot_nam and cot_quy:
            nam = pd.to_numeric(df[cot_nam], errors="coerce")
            quy = pd.to_numeric(df[cot_quy].astype(str).str.extract(r"([1-4])")[0], errors="coerce")
        else:
            cot_period = next((c for c in df.columns
                               if df[c].astype(str).head(8).map(lambda v: _doc_ky(v) is not None).mean() > 0.6), None)
            if cot_period is None:
                return None
            ky = df[cot_period].map(_doc_ky)
            nam = ky.map(lambda k: k[0] if k else None)
            quy = ky.map(lambda k: k[1] if k else None)
        df["_nam"], df["_quy"] = nam, quy
        df = df.dropna(subset=["_nam", "_quy"])
        df = df[(df["_quy"] >= 1) & (df["_quy"] <= 4)]
        df.index = pd.MultiIndex.from_arrays([df["_nam"].astype(int), df["_quy"].astype(int)], names=["nam", "quy"])
        df = df.drop(columns=["_nam", "_quy"])

    df = df.apply(pd.to_numeric, errors="coerce")
    df = df.loc[:, df.notna().any()]
    df = df[~df.index.duplicated(keep="first")].sort_index()
    return df if len(df) else None


def lay_bctc(ma: str) -> dict:
    """Trả về {'kqkd': DataFrame theo quý, 'chi_so': DataFrame theo quý} (có thể None)."""
    return {
        "kqkd": chuan_hoa_bctc(_goi_bctc(ma, "income")),
        "chi_so": chuan_hoa_bctc(_goi_bctc(ma, "ratio")),
    }


# ======================================================================
# CHỈ SỐ THẾ GIỚI (Yahoo Finance)
# ======================================================================
def lay_yahoo(ma_list: list[str], so_ngay: int = 420) -> dict[str, pd.Series]:
    """Trả về {mã: chuỗi giá đóng cửa}."""
    ket_qua: dict[str, pd.Series] = {}
    try:
        import yfinance as yf
    except ImportError:
        log.warning("Chưa cài yfinance")
        return ket_qua
    bat_dau = (date.today() - timedelta(days=so_ngay)).isoformat()
    try:
        df = yf.download(ma_list, start=bat_dau, progress=False, auto_adjust=False,
                         group_by="column", threads=True)
        close = df["Close"] if "Close" in df.columns.get_level_values(0) else df
        if isinstance(close, pd.Series):
            close = close.to_frame(ma_list[0])
        for ma in ma_list:
            if ma in close.columns:
                s = close[ma].dropna()
                if len(s) >= 5:
                    ket_qua[ma] = s
    except Exception as e:  # noqa: BLE001
        log.warning("Tải Yahoo theo nhóm lỗi: %s", e)
    # Thử lại từng mã bị thiếu
    for ma in [m for m in ma_list if m not in ket_qua]:
        try:
            s = yf.Ticker(ma).history(start=bat_dau, auto_adjust=False)["Close"].dropna()
            if len(s) >= 5:
                s.index = s.index.tz_localize(None) if s.index.tz is not None else s.index
                ket_qua[ma] = s
        except Exception as e:  # noqa: BLE001
            log.debug("Yahoo %s lỗi: %s", ma, e)
    return ket_qua


# ======================================================================
# LỢI SUẤT TRÁI PHIẾU (TradingView, dự phòng FRED)
# ======================================================================
def lay_tradingview(ma: str) -> dict | None:
    """Trả về {'gia': ..., 'thay_doi': ...} (thay_doi = chênh lệch tuyệt đối so với phiên trước)."""
    # Cách 1
    try:
        r = requests.get("https://scanner.tradingview.com/symbol",
                         params={"symbol": ma, "fields": "close,change_abs,change"},
                         headers=UA, timeout=15)
        if r.ok:
            d = r.json()
            if d.get("close") is not None:
                return {"gia": float(d["close"]), "thay_doi": float(d.get("change_abs") or 0)}
    except Exception as e:  # noqa: BLE001
        log.debug("TradingView symbol %s lỗi: %s", ma, e)
    # Cách 2
    for sc in ("cfd", "global", "bond"):
        try:
            r = requests.post(f"https://scanner.tradingview.com/{sc}/scan",
                              json={"symbols": {"tickers": [ma]}, "columns": ["close", "change_abs"]},
                              headers=UA, timeout=15)
            if r.ok:
                data = r.json().get("data") or []
                if data and data[0]["d"][0] is not None:
                    d = data[0]["d"]
                    return {"gia": float(d[0]), "thay_doi": float(d[1] or 0)}
        except Exception as e:  # noqa: BLE001
            log.debug("TradingView scan %s/%s lỗi: %s", sc, ma, e)
    return None


def lay_fred(ma: str) -> dict | None:
    """Số liệu FRED (thường theo tháng). Không cần API key."""
    try:
        r = requests.get("https://fred.stlouisfed.org/graph/fredgraph.csv", params={"id": ma},
                         headers=UA, timeout=20)
        r.raise_for_status()
        df = pd.read_csv(io.StringIO(r.text))
        df.columns = ["ngay", "gia"]
        df["gia"] = pd.to_numeric(df["gia"], errors="coerce")
        df = df.dropna()
        if len(df) >= 2:
            return {"gia": float(df["gia"].iloc[-1]),
                    "thay_doi": float(df["gia"].iloc[-1] - df["gia"].iloc[-2]),
                    "ghi_chu": f"số liệu tháng {str(df['ngay'].iloc[-1])[:7]}"}
    except Exception as e:  # noqa: BLE001
        log.debug("FRED %s lỗi: %s", ma, e)
    return None


# ======================================================================
# TỶ GIÁ VIETCOMBANK & GIÁ VÀNG SJC
# ======================================================================
def _so(v) -> float | None:
    try:
        return float(str(v).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def lay_ty_gia_vcb() -> dict | None:
    """Tỷ giá USD của Vietcombank: {'mua': ..., 'ban': ...} (đồng)."""
    try:
        r = requests.get("https://portal.vietcombank.com.vn/Usercontrols/TVPortal.TyGia/pXML.aspx",
                         headers=UA, timeout=20)
        r.raise_for_status()
        m = re.search(r'<Exrate[^>]*CurrencyCode="USD"[^>]*>', r.text)
        if m:
            the = m.group(0)
            mua = _so(re.search(r'Transfer="([^"]*)"', the).group(1))
            ban = _so(re.search(r'Sell="([^"]*)"', the).group(1))
            if mua and ban:
                return {"mua": mua, "ban": ban}
    except Exception as e:  # noqa: BLE001
        log.debug("VCB XML lỗi: %s", e)
    try:  # dự phòng: hàm có sẵn trong một số bản vnstock
        from vnstock.explorer.misc import vcb_exchange_rate
        df = vcb_exchange_rate(date=date.today().isoformat())
        df.columns = [bo_dau(c) for c in df.columns]
        dong = df[df.iloc[:, 0].astype(str).str.upper().str.contains("USD")].iloc[0]
        mua = _so(next(dong[c] for c in df.columns if "transfer" in c or "chuyen" in c))
        ban = _so(next(dong[c] for c in df.columns if "sell" in c or "ban" in c))
        if mua and ban:
            return {"mua": mua, "ban": ban}
    except Exception as e:  # noqa: BLE001
        log.debug("VCB vnstock lỗi: %s", e)
    return None


def _quy_ve_dong_luong(v: float | None) -> float | None:
    """Giá vàng có nơi ghi theo đồng, nghìn đồng hoặc triệu đồng/lượng -> đưa về đồng/lượng."""
    if not v:
        return None
    while v < 1_000_000:
        v *= 1000
    return v


def lay_gia_vang_sjc() -> dict | None:
    """Giá vàng miếng SJC: {'mua': ..., 'ban': ...} (đồng/lượng)."""
    try:
        r = requests.post("https://sjc.com.vn/GoldPrice/Services/PriceService.ashx",
                          headers=UA, timeout=20)
        r.raise_for_status()
        data = r.json().get("data") or []
        for d in data:
            ten = bo_dau(d.get("TypeName", ""))
            if "1l" in ten.replace(" ", "") or "mieng" in ten:
                mua, ban = _so(d.get("BuyValue")), _so(d.get("SellValue"))
                if mua and ban:
                    return {"mua": _quy_ve_dong_luong(mua), "ban": _quy_ve_dong_luong(ban)}
    except Exception as e:  # noqa: BLE001
        log.debug("SJC lỗi: %s", e)
    try:
        from vnstock.explorer.misc import sjc_gold_price
        df = sjc_gold_price()
        df.columns = [bo_dau(c) for c in df.columns]
        dong = df.iloc[0]
        mua = _so(next(dong[c] for c in df.columns if "buy" in c or "mua" in c))
        ban = _so(next(dong[c] for c in df.columns if "sell" in c or "ban" in c))
        if mua and ban:
            return {"mua": _quy_ve_dong_luong(mua), "ban": _quy_ve_dong_luong(ban)}
    except Exception as e:  # noqa: BLE001
        log.debug("SJC vnstock lỗi: %s", e)
    return None
