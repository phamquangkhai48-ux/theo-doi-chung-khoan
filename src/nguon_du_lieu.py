"""
Lấy dữ liệu từ các nguồn: Vietcap (giá cổ phiếu VN, VN30, BCTC — gọi thẳng API),
Yahoo Finance (chỉ số thế giới; dự phòng giá & BCTC cổ phiếu VN),
TradingView / FRED (lợi suất trái phiếu), Vietcombank (tỷ giá), SJC (giá vàng).

Nguyên tắc: mỗi hàm tự thử nhiều cách, lỗi ở một nguồn KHÔNG làm dừng chương trình.
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
    """Giãn cách các lần gọi Vietcap để không bị chặn."""
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


# ======================================================================
# KẾT NỐI VIETCAP (VCI) — gọi thẳng, không cần thư viện vnstock
# (vnstock đã bị gỡ khỏi PyPI từ cuối tháng 9/2026)
# ======================================================================
VCI_TRADING = "https://trading.vietcap.com.vn/api/"
VCI_IQ = "https://iq.vietcap.com.vn/api/iq-insight-service"
VCI_HEADERS = {
    **UA,
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "vi-VN,vi;q=0.9,en-US;q=0.8,en;q=0.7",
    "Content-Type": "application/json",
    "Referer": "https://trading.vietcap.com.vn/",
    "Origin": "https://trading.vietcap.com.vn",
}
_phien_vci: requests.Session | None = None


def phien_vci() -> requests.Session:
    """Mở một phiên làm việc với Vietcap (lấy cookie từ trang bảng giá)."""
    global _phien_vci
    if _phien_vci is None:
        s = requests.Session()
        s.headers.update(VCI_HEADERS)
        try:
            s.get("https://trading.vietcap.com.vn/priceboard", timeout=15)
        except Exception as e:  # noqa: BLE001
            log.debug("Mở phiên Vietcap lỗi: %s", e)
        _phien_vci = s
    return _phien_vci


def goi_vci(method: str, url: str, **kw):
    """Gọi API Vietcap, thử lại tối đa 3 lần."""
    loi = None
    for lan in range(3):
        nghi()
        try:
            r = phien_vci().request(method, url, timeout=25, **kw)
            if r.status_code == 429:
                time.sleep(10 * (lan + 1))
                continue
            r.raise_for_status()
            return r.json()
        except Exception as e:  # noqa: BLE001
            loi = e
            time.sleep(2 * (lan + 1))
    raise RuntimeError(f"Vietcap lỗi: {loi}")


# ======================================================================
# DANH SÁCH CỔ PHIẾU THEO NHÓM (VN30, VN100, ...)
# ======================================================================
SO_MA_NHOM = {"VN30": (25, 35), "VN100": (85, 110), "VNMIDCAP": (50, 90), "HNX30": (25, 35)}


def lay_danh_sach_nhom(nhom: str = "VN30") -> list[str]:
    nhom = nhom.upper()
    tu, den = SO_MA_NHOM.get(nhom, (5, 600))
    try:
        data = goi_vci("GET", VCI_TRADING + "price/symbols/getByGroup", params={"group": nhom})
        if isinstance(data, dict):
            data = data.get("data") or []
        ma = [str(x.get("symbol", "")).upper() for x in data if isinstance(x, dict)]
        ma = sorted({m for m in ma if re.fullmatch(r"[A-Z0-9]{3}", m)})
        if tu <= len(ma) <= den:
            return ma
        log.warning("Nhóm %s trả về %d mã — bất thường, bỏ qua", nhom, len(ma))
    except Exception as e:  # noqa: BLE001
        log.debug("Lấy nhóm %s lỗi: %s", nhom, e)
    return []


def lay_danh_sach_vn30() -> list[str]:
    return lay_danh_sach_nhom("VN30")


# ======================================================================
# GIÁ CỔ PHIẾU VIỆT NAM
# ======================================================================
def chuan_hoa_gia(df: pd.DataFrame, la_chi_so: bool = False) -> pd.DataFrame | None:
    """Đưa về dạng: index = ngày, cột open/high/low/close/volume; giá cổ phiếu theo NGHÌN đồng."""
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
    if not la_chi_so and df["close"].median() > 1000:
        for c in ["open", "high", "low", "close"]:
            df[c] = df[c] / 1000
    return df


def _bang_tu_vci(d: dict, la_chi_so: bool = False) -> pd.DataFrame | None:
    if not isinstance(d, dict) or not d.get("c"):
        return None
    t = pd.to_numeric(pd.Series(d["t"]), errors="coerce")
    df = pd.DataFrame({
        "time": (pd.to_datetime(t, unit="s") + pd.Timedelta(hours=7)).dt.normalize(),
        "open": d["o"], "high": d["h"], "low": d["l"], "close": d["c"], "volume": d["v"],
    })
    return chuan_hoa_gia(df, la_chi_so)


def _goi_bieu_do(ma_list: list[str], so_ngay: int) -> list:
    so_phien = int(so_ngay * 5 / 7) + 10
    den = int(time.time()) + 86400
    data = goi_vci("POST", VCI_TRADING + "chart/OHLCChart/gap-chart",
                   json={"timeFrame": "ONE_DAY", "symbols": ma_list, "to": den, "countBack": so_phien})
    if isinstance(data, dict):
        data = data.get("data") or []
    return data if isinstance(data, list) else []


def _gia_vci(ma: str, so_ngay: int, la_chi_so: bool = False) -> pd.DataFrame | None:
    data = _goi_bieu_do([ma], so_ngay)
    return _bang_tu_vci(data[0], la_chi_so) if data else None


def lay_gia_nhieu_ma(ds: list[str], so_ngay: int = 420, la_chi_so: bool = False,
                     lo: int = 20) -> dict[str, tuple[pd.DataFrame, str]]:
    """
    Lấy giá nhiều mã: gọi Vietcap theo lô (nhanh), mã nào thiếu thì gọi riêng,
    vẫn thiếu thì thử Yahoo. Trả về {mã: (bảng giá, nguồn)}.
    """
    kq: dict[str, tuple[pd.DataFrame, str]] = {}
    for i in range(0, len(ds), lo):
        nhom = ds[i:i + lo]
        try:
            data = _goi_bieu_do(nhom, so_ngay)
            # Chỉ nhận khi mỗi phần tử ghi rõ mã (tránh gán nhầm giá giữa các mã)
            goc = {m.upper(): m for m in nhom}
            for d in data:
                if isinstance(d, dict) and d.get("symbol"):
                    ma = goc.get(str(d["symbol"]).upper())
                    if ma:
                        df = _bang_tu_vci(d, la_chi_so)
                        if df is not None and len(df) >= 30:
                            kq[ma] = (df, "vietcap")
        except Exception as e:  # noqa: BLE001
            log.debug("Lô %s lỗi: %s", nhom[:3], e)
    thieu = [m for m in ds if m not in kq]
    if thieu:
        log.info("Lấy riêng %d mã còn thiếu", len(thieu))
    for ma in thieu:
        if la_chi_so:
            try:
                df = _gia_vci(ma, so_ngay, True)
                if df is not None and len(df) >= 30:
                    kq[ma] = (df, "vietcap")
            except Exception as e:  # noqa: BLE001
                log.debug("Chỉ số %s lỗi: %s", ma, e)
            continue
        df, nguon = lay_gia_co_phieu(ma, so_ngay)
        if df is not None:
            kq[ma] = (df, nguon)
    return kq


def lay_gia_co_phieu(ma: str, so_ngay: int = 420) -> tuple[pd.DataFrame | None, str]:
    """Trả về (bảng giá, tên nguồn). Thử Vietcap trước, dự phòng Yahoo Finance."""
    try:
        df = _gia_vci(ma, so_ngay)
        if df is not None and len(df) >= 30:
            return df, "vietcap"
    except Exception as e:  # noqa: BLE001
        log.debug("%s: Vietcap lỗi: %s", ma, e)

    try:
        import yfinance as yf
        bat_dau = (date.today() - timedelta(days=so_ngay)).isoformat()
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
_TEN_CHI_TIEU: dict[str, str] = {}
_DOI_TEN_CHI_SO = {"roe": "roe", "pe": "p/e", "pb": "p/b", "debtToEquity": "no/vcsh",
                   "debtPerEquity": "no/vcsh (2)", "year": "year", "quarter": "quarter"}


def _ten_chi_tieu(ma: str) -> dict[str, str]:
    """Bảng đổi mã chỉ tiêu Vietcap (vd 'isa3') sang tên tiếng Việt. Lấy một lần."""
    if not _TEN_CHI_TIEU:
        data = (goi_vci("GET", f"{VCI_IQ}/v1/company/{ma}/financial-statement/metrics") or {}).get("data") or {}
        uu_tien = sorted(data.keys(), key=lambda k: 0 if "INCOME" in str(k).upper() else 1)
        for k in uu_tien:
            for dong in data[k] or []:
                f = dong.get("field")
                ten = dong.get("titleVi") or dong.get("fullTitleVi") or dong.get("titleEn")
                if f and ten and f not in _TEN_CHI_TIEU:
                    _TEN_CHI_TIEU[f] = ten
    return _TEN_CHI_TIEU


def _bctc_vci(ma: str, loai: str) -> pd.DataFrame | None:
    if loai == "income":
        data = (goi_vci("GET", f"{VCI_IQ}/v1/company/{ma}/financial-statement",
                        params={"section": "INCOME_STATEMENT"}) or {}).get("data") or {}
        quy = data.get("quarters") or []
        if not quy:
            return None
        df = pd.DataFrame(quy)
        try:
            ten = _ten_chi_tieu(ma)
            df = df.rename(columns={c: ten[c] for c in df.columns if c in ten})
        except Exception as e:  # noqa: BLE001
            log.debug("Không lấy được tên chỉ tiêu: %s", e)
        return df
    data = (goi_vci("GET", f"{VCI_IQ}/v1/company/{ma}/statistics-financial") or {}).get("data") or []
    if not data:
        return None
    df = pd.DataFrame(data)
    return df.rename(columns={c: v for c, v in _DOI_TEN_CHI_SO.items() if c in df.columns})


def _bctc_yahoo(ma: str, loai: str) -> pd.DataFrame | None:
    """Dự phòng: báo cáo kết quả kinh doanh theo quý từ Yahoo Finance (thường chỉ 4–5 quý)."""
    if loai != "income":
        return None
    import yfinance as yf
    bang = yf.Ticker(f"{ma}.VN").quarterly_income_stmt
    if bang is None or bang.empty:
        return None
    df = bang.T.copy()
    ngay = pd.to_datetime(df.index)
    df.insert(0, "year", ngay.year)
    df.insert(1, "quarter", (ngay.month - 1) // 3 + 1)
    return df.reset_index(drop=True)


def _goi_bctc(ma: str, loai: str):
    """loai: 'income' hoặc 'ratio'. Trả về DataFrame thô."""
    for ham in (_bctc_vci, _bctc_yahoo):
        try:
            df = ham(ma, loai)
            if df is not None and len(df) > 0:
                return df
        except Exception as e:  # noqa: BLE001
            log.debug("%s: %s %s lỗi: %s", ma, ham.__name__, loai, e)
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
    return None
