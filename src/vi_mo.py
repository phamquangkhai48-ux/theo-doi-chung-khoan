"""Theo dõi chỉ số vĩ mô: chứng khoán thế giới, tỷ giá, DXY, vàng, Bitcoin, lợi suất trái phiếu."""
from __future__ import annotations

import logging

import pandas as pd

from . import nguon_du_lieu as nd
from .bao_cao import so

log = logging.getLogger("vi_mo")
GRAM_MOI_OUNCE = 31.1035
GRAM_MOI_LUONG = 37.5


def _thong_ke(s: pd.Series, la_loi_suat: bool) -> dict:
    """Mức hiện tại, thay đổi 1/5/20 phiên (%, hoặc điểm % nếu là lợi suất), vị trí so với MA50/MA200."""
    def doi(n):
        if len(s) <= n:
            return None
        cu, moi = s.iloc[-1 - n], s.iloc[-1]
        return float(moi - cu) if la_loi_suat else float((moi / cu - 1) * 100)

    ma50 = s.rolling(50).mean().iloc[-1] if len(s) >= 50 else None
    ma200 = s.rolling(200).mean().iloc[-1] if len(s) >= 200 else None
    ma50_hq = s.rolling(50).mean().iloc[-2] if len(s) >= 51 else None
    return {
        "gia": float(s.iloc[-1]),
        "ngay": s.index[-1].date().isoformat() if hasattr(s.index[-1], "date") else str(s.index[-1]),
        "d1": doi(1), "d5": doi(5), "d20": doi(20),
        "tren_ma50": None if ma50 is None else bool(s.iloc[-1] > ma50),
        "tren_ma200": None if ma200 is None else bool(s.iloc[-1] > ma200),
        "vua_cat_ma50": (None if ma50 is None or ma50_hq is None else
                         ("lên" if s.iloc[-2] <= ma50_hq and s.iloc[-1] > ma50 else
                          "xuống" if s.iloc[-2] >= ma50_hq and s.iloc[-1] < ma50 else None)),
    }


def thu_thap(cfg: dict, lay_trong_nuoc: bool = True) -> dict:
    """Thu thập toàn bộ số liệu vĩ mô và tạo danh sách cảnh báo."""
    vm = cfg["vi_mo"]
    ds = vm["chi_so"]
    du_lieu = nd.lay_yahoo([x["ma"] for x in ds])

    ket_qua = {"chi_so": [], "loi_suat": [], "trong_nuoc": {}, "canh_bao": [], "loi": []}

    for x in ds:
        s = du_lieu.get(x["ma"])
        if s is None:
            ket_qua["loi"].append(x["ten"])
            continue
        tk = _thong_ke(s, x.get("la_loi_suat", False))
        tk.update(ten=x["ten"], ma=x["ma"], nhom=x.get("nhom", ""), la_loi_suat=x.get("la_loi_suat", False))
        ket_qua["chi_so"].append(tk)
        # cảnh báo biến động 1 phiên
        if tk["d1"] is not None and abs(tk["d1"]) >= x.get("nguong_ngay", 999):
            don_vi = " điểm %" if tk["la_loi_suat"] else "%"
            ket_qua["canh_bao"].append(f"{x['ten']} biến động mạnh: {'+' if tk['d1'] > 0 else ''}{so(tk['d1'], 2)}{don_vi} trong phiên")
        if tk["vua_cat_ma50"]:
            ket_qua["canh_bao"].append(f"{x['ten']} vừa cắt {tk['vua_cat_ma50']} đường MA50")

    # Lợi suất Nhật, Việt Nam
    for x in vm.get("loi_suat_khac", []):
        d = nd.lay_tradingview(x["ma_tradingview"]) if x.get("ma_tradingview") else None
        if d is None and x.get("ma_fred"):
            d = nd.lay_fred(x["ma_fred"])
        if d is None:
            ket_qua["loi"].append(x["ten"])
            continue
        d["ten"] = x["ten"]
        ket_qua["loi_suat"].append(d)
        if not d.get("ghi_chu") and abs(d["thay_doi"]) >= x.get("nguong_ngay", 999):
            ket_qua["canh_bao"].append(f"{x['ten']} thay đổi mạnh: {'+' if d['thay_doi'] > 0 else ''}{so(d['thay_doi'], 2)} điểm %")

    # Cảnh báo tổng hợp
    tim = {c["ma"]: c for c in ket_qua["chi_so"]}
    dxy, usdvnd, us10 = tim.get("DX-Y.NYB"), tim.get("USDVND=X"), tim.get("^TNX")
    if dxy and dxy["d5"] is not None and dxy["d5"] >= vm["dxy_tang_5_phien"]:
        ket_qua["canh_bao"].append(f"DXY tăng {so(dxy['d5'], 1)}% trong 5 phiên → áp lực lên tỷ giá và dòng vốn ngoại")
    if usdvnd and usdvnd["d20"] is not None and usdvnd["d20"] >= vm["usdvnd_tang_20_phien"]:
        ket_qua["canh_bao"].append(f"USD/VND tăng {so(usdvnd['d20'], 2)}% trong 20 phiên → áp lực tỷ giá")
    if us10 and us10["d5"] is not None and us10["d5"] >= vm["loi_suat_my_tang_5_phien"]:
        ket_qua["canh_bao"].append(f"Lợi suất 10N Mỹ tăng {so(us10['d5'], 2)} điểm % trong 5 phiên")

    # Trong nước: tỷ giá VCB, vàng SJC
    if lay_trong_nuoc:
        vcb = nd.lay_ty_gia_vcb()
        sjc = nd.lay_gia_vang_sjc()
        ket_qua["trong_nuoc"] = {"vcb": vcb, "sjc": sjc}
        if vcb is None:
            ket_qua["loi"].append("Tỷ giá Vietcombank")
        if sjc is None:
            ket_qua["loi"].append("Giá vàng SJC")
        vang_tg = tim.get("GC=F")
        ty_gia = (vcb or {}).get("ban") or (usdvnd or {}).get("gia")
        if sjc and vang_tg and ty_gia:
            quy_doi = vang_tg["gia"] * ty_gia / GRAM_MOI_OUNCE * GRAM_MOI_LUONG
            chenh = (sjc["ban"] / quy_doi - 1) * 100
            ket_qua["trong_nuoc"]["vang_quy_doi"] = quy_doi
            ket_qua["trong_nuoc"]["chenh_lech_vang"] = chenh
            if chenh >= vm["chenh_lech_vang_sjc_canh_bao"]:
                ket_qua["canh_bao"].append(f"Vàng SJC cao hơn vàng thế giới quy đổi {so(chenh, 0)}%")
    return ket_qua
