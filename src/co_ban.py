"""Đọc báo cáo tài chính theo quý và tạo tín hiệu cơ bản."""
from __future__ import annotations

import math

import pandas as pd

from .bao_cao import so

# Tên cột được so khớp sau khi bỏ dấu + chữ thường. Thứ tự = ưu tiên.
# Mỗi mục: (các cụm BẮT BUỘC có, các cụm KHÔNG được có)
MAU_DOANH_THU = [
    (["doanh thu thuan"], ["gia von", "tang truong", "%"]),
    (["net revenue"], ["cost", "growth", "%"]),
    (["net sales"], ["cost", "growth", "%"]),
    (["tong thu nhap hoat dong"], ["%", "tang truong"]),        # ngân hàng
    (["total operating income"], ["%", "growth"]),
    (["thu nhap lai thuan"], ["%", "tang truong"]),
    (["net interest income"], ["%", "growth"]),
    (["doanh thu"], ["gia von", "chi phi", "tai chinh", "tang truong", "%", "khac"]),
    (["revenue"], ["cost", "financial", "growth", "%", "other"]),
]
MAU_LOI_NHUAN = [
    (["co dong", "cong ty me"], ["truoc thue", "%", "tang truong", "khong kiem soat"]),
    (["attributable to parent"], ["before", "%", "growth", "minority", "non-controlling"]),
    (["parent company"], ["before", "%", "growth", "minority", "non-controlling"]),
    (["loi nhuan sau thue"], ["truoc", "%", "tang truong", "khong kiem soat", "thieu so"]),
    (["net profit"], ["before", "%", "growth", "minority", "margin"]),
    (["profit after tax"], ["before", "%", "growth", "minority"]),
]
MAU_LOI_NHUAN_GOP = [
    (["loi nhuan gop"], ["%", "bien", "tang truong"]),
    (["gross profit"], ["%", "margin", "growth"]),
]
MAU_ROE = [(["roe"], []), (["loi nhuan tren von chu"], [])]
MAU_PE = [(["p/e"], ["forward"]), (["pe"], []), (["gia/thu nhap"], [])]
MAU_NO_VCSH = [
    (["no/vcsh"], []), (["debt/equity"], []), (["no vay/vcsh"], []),
    (["(vay nh+dh)/vcsh"], []), (["(st+lt borrowings)/equity"], []), (["no/von chu"], []),
]


def tim_cot(cot_list, mau) -> str | None:
    for bat_buoc, loai_tru in mau:
        for c in cot_list:
            ten = str(c)
            ten_gon = ten.replace(" ", "")
            khop = all((k in ten) or (k.replace(" ", "") in ten_gon) for k in bat_buoc)
            if khop and not any(x in ten for x in loai_tru):
                # "pe" quá ngắn: yêu cầu là cả một từ
                if bat_buoc == ["pe"] and not any(t in ("pe", "p/e") for t in ten.replace("(", " ").replace(")", " ").split()):
                    continue
                return c
    return None


def _gia_tri(df: pd.DataFrame | None, cot: str | None, ky) -> float | None:
    if df is None or cot is None or ky not in df.index:
        return None
    v = df.at[ky, cot]
    if isinstance(v, pd.Series):
        v = v.iloc[0]
    return None if pd.isna(v) else float(v)


def _pct(moi, cu) -> float | None:
    if moi is None or cu is None or cu == 0:
        return None
    if cu < 0:                         # từ lỗ sang lãi / lỗ ít hơn: tính theo trị tuyệt đối
        return (moi - cu) / abs(cu) * 100
    return (moi / cu - 1) * 100


def _ve_phan_tram(v):
    """ROE có nguồn ghi 0.18, có nguồn ghi 18 -> đưa về 18."""
    if v is None or math.isnan(v):
        return None
    return v * 100 if abs(v) <= 1.5 else v


def phan_tich(ma: str, bctc: dict, cfg: dict, la_tai_chinh: bool) -> dict:
    """
    Trả về:
      ky_moi_nhat: 'Q2/2026'; cac chỉ tiêu tăng trưởng; danh sách tín hiệu tốt/xấu; dat_chuan (bool)
    """
    kq = {"ma": ma, "ky_moi_nhat": None, "tot": [], "xau": [], "dat_chuan": False, "loi": None}
    kqkd, chi_so = bctc.get("kqkd"), bctc.get("chi_so")
    if kqkd is None and chi_so is None:
        kq["loi"] = "không lấy được BCTC"
        return kq

    goc = kqkd if kqkd is not None else chi_so
    ky = goc.index[-1]
    nam, quy = ky
    ky_cung_ky = (nam - 1, quy)
    kq["ky_moi_nhat"] = f"Q{quy}/{nam}"
    kq["ky_key"] = f"{nam}Q{quy}"

    # -------- tăng trưởng
    if kqkd is not None:
        c_dt = tim_cot(kqkd.columns, MAU_DOANH_THU)
        c_ln = tim_cot(kqkd.columns, MAU_LOI_NHUAN)
        c_lng = tim_cot(kqkd.columns, MAU_LOI_NHUAN_GOP)

        dt, dt_ck = _gia_tri(kqkd, c_dt, ky), _gia_tri(kqkd, c_dt, ky_cung_ky)
        ln, ln_ck = _gia_tri(kqkd, c_ln, ky), _gia_tri(kqkd, c_ln, ky_cung_ky)
        kq["doanh_thu_yoy"] = _pct(dt, dt_ck)
        kq["loi_nhuan_yoy"] = _pct(ln, ln_ck)
        kq["loi_nhuan"] = ln

        # Lợi nhuận 4 quý gần nhất so với 4 quý trước đó
        if c_ln and len(kqkd) >= 8:
            s = kqkd[c_ln].dropna()
            if len(s) >= 8:
                kq["loi_nhuan_4q_yoy"] = _pct(s.iloc[-4:].sum(), s.iloc[-8:-4].sum())

        # Biên lợi nhuận gộp
        if c_lng and c_dt and not la_tai_chinh:
            lng, lng_ck = _gia_tri(kqkd, c_lng, ky), _gia_tri(kqkd, c_lng, ky_cung_ky)
            if dt and dt_ck and lng is not None and lng_ck is not None:
                kq["bien_gop"] = lng / dt * 100
                kq["bien_gop_ck"] = lng_ck / dt_ck * 100

        # Có tăng trưởng liên tiếp 2 quý?
        if c_ln:
            ky_truoc = kqkd.index[-2] if len(kqkd) >= 2 else None
            if ky_truoc:
                ln_t = _gia_tri(kqkd, c_ln, ky_truoc)
                ln_t_ck = _gia_tri(kqkd, c_ln, (ky_truoc[0] - 1, ky_truoc[1]))
                kq["loi_nhuan_yoy_quy_truoc"] = _pct(ln_t, ln_t_ck)

    # -------- chỉ số
    if chi_so is not None:
        ky_cs = chi_so.index[-1]
        kq["roe"] = _ve_phan_tram(_gia_tri(chi_so, tim_cot(chi_so.columns, MAU_ROE), ky_cs))
        kq["pe"] = _gia_tri(chi_so, tim_cot(chi_so.columns, MAU_PE), ky_cs)
        kq["no_vcsh"] = _gia_tri(chi_so, tim_cot(chi_so.columns, MAU_NO_VCSH), ky_cs)

    # -------- tín hiệu
    tot, xau = kq["tot"], kq["xau"]
    dt_y, ln_y = kq.get("doanh_thu_yoy"), kq.get("loi_nhuan_yoy")
    ln_y_truoc = kq.get("loi_nhuan_yoy_quy_truoc")
    if dt_y is not None and dt_y >= cfg["doanh_thu_tang_yoy"]:
        tot.append(f"Doanh thu +{so(dt_y, 0)}% so với cùng kỳ")
    if ln_y is not None:
        if ln_y >= cfg["loi_nhuan_tang_yoy"]:
            tot.append(f"LNST +{so(ln_y, 0)}% so với cùng kỳ")
            if ln_y_truoc is not None and ln_y_truoc >= cfg["loi_nhuan_tang_yoy"]:
                tot.append("LNST tăng mạnh 2 quý liên tiếp")
        elif ln_y <= cfg["loi_nhuan_giam_canh_bao"]:
            xau.append(f"LNST {so(ln_y, 0)}% so với cùng kỳ")
    if kq.get("loi_nhuan") is not None and kq["loi_nhuan"] < 0:
        xau.append("Lỗ trong quý")
    bg, bg_ck = kq.get("bien_gop"), kq.get("bien_gop_ck")
    if bg is not None and bg_ck is not None:
        if bg - bg_ck >= 1:
            tot.append(f"Biên gộp cải thiện {so(bg_ck, 1)}% → {so(bg, 1)}%")
        elif bg_ck - bg >= 2:
            xau.append(f"Biên gộp giảm {so(bg_ck, 1)}% → {so(bg, 1)}%")
    roe = kq.get("roe")
    if roe is not None:
        (tot if roe >= cfg["roe_toi_thieu"] else xau).append(f"ROE {so(roe, 1)}%")
    pe = kq.get("pe")
    if pe is not None and 0 < pe <= cfg["pe_toi_da"]:
        tot.append(f"P/E {so(pe, 1)}")
    elif pe is not None and pe > cfg["pe_toi_da"]:
        xau.append(f"P/E cao {so(pe, 1)}")
    nv = kq.get("no_vcsh")
    if nv is not None and not la_tai_chinh and nv > cfg["no_tren_von_chu_toi_da"]:
        xau.append(f"Nợ/VCSH {so(nv, 2)} lần")

    kq["dat_chuan"] = (
        ln_y is not None and ln_y >= cfg["loi_nhuan_tang_yoy"]
        and (roe is None or roe >= cfg["roe_toi_thieu"])
        and not any(x.startswith("Lỗ") for x in xau)
    )
    return kq
