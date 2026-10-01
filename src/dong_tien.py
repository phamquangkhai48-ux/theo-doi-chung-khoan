"""
Dữ liệu dòng tiền trong phiên:
  - Bảng giá: giá, tổng khối lượng, giá trị, khối ngoại mua/bán (KBS, dự phòng Vietcap)
  - Khớp lệnh từng lệnh kèm chiều mua/bán chủ động (Vietcap, dự phòng KBS)
và các hàm tính: khối lượng bất thường, mua/bán chủ động, lệnh lớn.

Đơn vị: giá theo NGHÌN đồng, khối lượng theo cổ phiếu, giá trị theo TỶ đồng.
"""
from __future__ import annotations

import logging
from datetime import datetime

import pandas as pd
import requests

from . import nguon_du_lieu as nd

log = logging.getLogger("dong_tien")
KBS = "https://kbbuddywts.kbsec.com.vn/iis-server/investment"
KBS_HEADERS = {**nd.UA, "Accept": "application/json, text/plain, */*", "Content-Type": "application/json",
               "Accept-Language": "vi-VN,vi;q=0.9,en;q=0.8", "x-lang": "vi"}


def _so(v) -> float | None:
    try:
        if v is None or v == "":
            return None
        return float(str(v).replace(",", ""))
    except (TypeError, ValueError):
        return None


def _nghin(v: float | None) -> float | None:
    """Giá có nguồn ghi theo đồng (24850), có nguồn theo nghìn (24.85) -> nghìn đồng."""
    if v is None:
        return None
    return v / 1000 if v > 1000 else v


def gt_ty(gia_nghin: float, kl: float) -> float:
    """Giá trị (tỷ đồng) = giá (nghìn đồng) × khối lượng."""
    return gia_nghin * kl / 1e6


# ======================================================================
# BẢNG GIÁ
# ======================================================================
def _bang_gia_kbs(ds: list[str]) -> dict[str, dict]:
    kq = {}
    for i in range(0, len(ds), 50):
        nd.nghi()
        r = requests.post(f"{KBS}/stock/iss", json={"code": ",".join(ds[i:i + 50])},
                          headers=KBS_HEADERS, timeout=30)
        r.raise_for_status()
        data = r.json()
        if isinstance(data, dict):
            data = data.get("data") or []
        for d in data or []:
            ma = str(d.get("SB") or "").upper()
            gia = _nghin(_so(d.get("CP"))) or _nghin(_so(d.get("RE")))
            tc = _nghin(_so(d.get("RE")))
            kl = _so(d.get("TT"))
            if not ma or not gia or kl is None:
                continue
            gt = _so(d.get("TV"))
            kq[ma] = {
                "gia": gia, "tham_chieu": tc,
                "pct": (gia / tc - 1) * 100 if tc else 0.0,
                "kl": kl,
                "gt": gt / 1e9 if gt and gt > 1e6 else (gt_ty(gia, kl) if kl else 0.0),
                "nn_mua": _so(d.get("FB")) or 0.0, "nn_ban": _so(d.get("FS")) or 0.0,
                "co_nn": d.get("FB") is not None,
            }
    return kq


def _tim(d: dict, *goi_y: str):
    """Tìm giá trị trong dict lồng nhau theo tên khóa (không phân biệt hoa thường)."""
    phang = {}

    def duyet(x, tien_to=""):
        if isinstance(x, dict):
            for k, v in x.items():
                duyet(v, f"{tien_to}{k}".lower() + ".")
        else:
            phang[tien_to.rstrip(".")] = x
    duyet(d)
    for g in goi_y:
        for k, v in phang.items():
            if k.endswith(g.lower()):
                return v
    return None


def _bang_gia_vci(ds: list[str]) -> dict[str, dict]:
    kq = {}
    for i in range(0, len(ds), 50):
        data = nd.goi_vci("POST", nd.VCI_TRADING + "price/symbols/getList", json={"symbols": ds[i:i + 50]})
        if isinstance(data, dict):
            data = data.get("data") or []
        for d in data or []:
            ma = str(_tim(d, "listinginfo.symbol", "symbol") or "").upper()
            gia = _nghin(_so(_tim(d, "matchprice.matchprice", "matchprice")))
            tc = _nghin(_so(_tim(d, "referenceprice", "refprice", "reference")))
            kl = _so(_tim(d, "accumulatedvolume", "totalvolume"))
            if not ma or not gia or kl is None:
                continue
            nn_mua, nn_ban = _so(_tim(d, "foreignbuyvolume")), _so(_tim(d, "foreignsellvolume"))
            gt = _so(_tim(d, "accumulatedvalue", "totalvalue"))
            kq[ma] = {
                "gia": gia, "tham_chieu": tc, "pct": (gia / tc - 1) * 100 if tc else 0.0, "kl": kl,
                "gt": gt / 1e9 if gt and gt > 1e6 else gt_ty(gia, kl),
                "nn_mua": nn_mua or 0.0, "nn_ban": nn_ban or 0.0, "co_nn": nn_mua is not None,
            }
    return kq


def lay_bang_gia(ds: list[str]) -> tuple[dict[str, dict], str]:
    for ten, ham in (("kbs", _bang_gia_kbs), ("vietcap", _bang_gia_vci)):
        try:
            kq = ham(ds)
            if len(kq) >= max(1, len(ds) // 2):
                return kq, ten
            log.info("Bảng giá %s chỉ có %d/%d mã", ten, len(kq), len(ds))
        except Exception as e:  # noqa: BLE001
            log.debug("Bảng giá %s lỗi: %s", ten, e)
    return {}, ""


# ======================================================================
# KHỚP LỆNH TỪNG LỆNH
# ======================================================================
def _chieu(v) -> str:
    v = str(v or "").strip().lower()
    if v in ("b", "buy", "bu", "mua"):
        return "mua"
    if v in ("s", "sell", "sd", "ban", "bán"):
        return "ban"
    return ""                                  # ATO/ATC/không rõ


def _khop_vci(ma: str) -> pd.DataFrame | None:
    data = nd.goi_vci("POST", nd.VCI_TRADING + "market-watch/LEData/getAll",
                      json={"symbol": ma, "limit": 30000, "truncTime": None})
    if isinstance(data, dict):
        data = data.get("data") or []
    if not data:
        return None
    df = pd.DataFrame(data)
    if not {"truncTime", "matchPrice", "matchVol"} <= set(df.columns):
        return None
    t = pd.to_numeric(df["truncTime"], errors="coerce")
    out = pd.DataFrame({
        "time": pd.to_datetime(t, unit="s") + pd.Timedelta(hours=7),
        "gia": pd.to_numeric(df["matchPrice"], errors="coerce").map(_nghin),
        "kl": pd.to_numeric(df["matchVol"], errors="coerce"),
        "chieu": df.get("matchType", pd.Series([""] * len(df))).map(_chieu),
    })
    return out.dropna(subset=["time", "gia", "kl"])


def _khop_kbs(ma: str) -> pd.DataFrame | None:
    nd.nghi()
    r = requests.get(f"{KBS}/trade/history/{ma}", params={"page": 1, "limit": 10000},
                     headers=KBS_HEADERS, timeout=30)
    r.raise_for_status()
    data = (r.json() or {}).get("data") or []
    if not data:
        return None
    df = pd.DataFrame(data)
    hom_nay = datetime.now().strftime("%Y-%m-%d")
    out = pd.DataFrame({
        "time": pd.to_datetime(hom_nay + " " + df["FT"].astype(str), errors="coerce"),
        "gia": pd.to_numeric(df["FMP"], errors="coerce").map(_nghin),
        "kl": pd.to_numeric(df["FV"], errors="coerce"),
        "chieu": df.get("LC", pd.Series([""] * len(df))).map(_chieu),
    })
    return out.dropna(subset=["time", "gia", "kl"])


def lay_khop_lenh(ma: str) -> pd.DataFrame | None:
    """Bảng các lệnh khớp trong ngày: time, gia (nghìn), kl, chieu ('mua'/'ban'/'')."""
    for ham in (_khop_vci, _khop_kbs):
        try:
            df = ham(ma)
            if df is not None and len(df):
                df = df.sort_values("time").reset_index(drop=True)
                df["gt"] = df["gia"] * df["kl"] / 1e6      # tỷ đồng
                return df
        except Exception as e:  # noqa: BLE001
            log.debug("%s khớp lệnh %s lỗi: %s", ma, ham.__name__, e)
    return None


def phan_tich_lenh(df: pd.DataFrame, nguong_lenh_lon_ty: float, tu: datetime | None = None) -> dict:
    """Tổng mua/bán chủ động và các lệnh lớn (từ thời điểm `tu` nếu có)."""
    if tu is not None:
        df = df[df["time"] > tu]
    mua = float(df.loc[df["chieu"] == "mua", "gt"].sum())
    ban = float(df.loc[df["chieu"] == "ban", "gt"].sum())
    lon = df[df["gt"] >= nguong_lenh_lon_ty].sort_values("gt", ascending=False)
    return {
        "mua": mua, "ban": ban, "tong": float(df["gt"].sum()),
        "ti_le_mua": mua / (mua + ban) * 100 if mua + ban > 0 else None,
        "so_lenh_lon": len(lon),
        "lon_mua": float(lon.loc[lon["chieu"] == "mua", "gt"].sum()),
        "lon_ban": float(lon.loc[lon["chieu"] == "ban", "gt"].sum()),
        "lenh_lon": lon.head(5)[["time", "gia", "kl", "gt", "chieu"]].to_dict("records"),
    }


def nguong_lenh_lon(cfg_dt: dict, gt_tb20_ty: float | None) -> float:
    """Lệnh lớn = lớn hơn cả mức tối thiểu (tỷ) lẫn x% giá trị giao dịch trung bình 1 phiên."""
    toi_thieu = float(cfg_dt.get("lenh_lon_ty", 2))
    ti_le = float(cfg_dt.get("lenh_lon_phan_tram_gtgd", 0.5)) / 100
    return max(toi_thieu, (gt_tb20_ty or 0) * ti_le)


def mo_ta_lenh(l: dict) -> str:
    t = pd.Timestamp(l["time"]).strftime("%H:%M")
    huong = {"mua": "MUA", "ban": "BÁN"}.get(l["chieu"], "ATO/ATC")
    return f"{huong} {nd_so(l['gt'])} tỷ ({nd_so(l['kl'] / 1000, 0)}k cp @ {nd_so(l['gia'], 2)}, {t})"


def nd_so(x, le=1) -> str:
    s = f"{x:,.{le}f}"
    return s.replace(",", "_").replace(".", ",").replace("_", ".")
