"""Soạn nội dung bản tin gửi Telegram (định dạng HTML của Telegram)."""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from .thong_bao import esc

GIO_VN = ZoneInfo("Asia/Ho_Chi_Minh")

CO = {"my": "🇺🇸", "chau_au": "🇪🇺", "chau_a": "🌏", "tien_te": "💵", "hang_hoa": "🛢", "loi_suat": "📈"}
TEN_NHOM = {"my": "Chứng khoán Mỹ", "chau_au": "Chứng khoán châu Âu", "chau_a": "Chứng khoán châu Á", "tien_te": "Tiền tệ",
            "hang_hoa": "Hàng hóa & Bitcoin", "loi_suat": "Lợi suất trái phiếu 10 năm"}


def so(x, le=2) -> str:
    """Định dạng số kiểu Việt Nam: 1.234,56"""
    if x is None:
        return "—"
    s = f"{x:,.{le}f}"
    return s.replace(",", "_").replace(".", ",").replace("_", ".")


def dau(x, le=2, don_vi="%") -> str:
    if x is None:
        return "—"
    mui = "🟢" if x > 0 else "🔴" if x < 0 else "⚪"
    return f"{mui} {'+' if x > 0 else ''}{so(x, le)}{don_vi}"


# ======================================================================
def ban_tin_vi_mo(vm: dict, tieu_de: str) -> str:
    dong = [f"<b>{esc(tieu_de)}</b> — {datetime.now(GIO_VN).strftime('%d/%m/%Y')}", ""]

    if vm["canh_bao"]:
        dong.append("<b>⚠️ Cảnh báo</b>")
        dong += [f"• {esc(c)}" for c in vm["canh_bao"]]
        dong.append("")

    for nhom in ["my", "chau_au", "chau_a", "tien_te", "hang_hoa", "loi_suat"]:
        muc = [c for c in vm["chi_so"] if c["nhom"] == nhom]
        if nhom == "loi_suat":
            muc_khac = vm.get("loi_suat", [])
        else:
            muc_khac = []
        if not muc and not muc_khac:
            continue
        dong.append(f"<b>{CO[nhom]} {esc(TEN_NHOM[nhom])}</b>")
        for c in muc:
            if c["la_loi_suat"]:
                dong.append(f"• {esc(c['ten'])}: <b>{so(c['gia'], 2)}%</b> {dau(c['d1'], 2, ' điểm')} "
                            f"| 5 phiên: {'+' if (c['d5'] or 0) > 0 else ''}{so(c['d5'], 2)}")
            else:
                le = 0 if c["gia"] > 5000 else 2
                xh = ""
                if c["tren_ma200"] is not None:
                    xh = " | trên MA200" if c["tren_ma200"] else " | dưới MA200"
                dong.append(f"• {esc(c['ten'])}: <b>{so(c['gia'], le)}</b> {dau(c['d1'])} "
                            f"| 20 phiên: {'+' if (c['d20'] or 0) > 0 else ''}{so(c['d20'], 1)}%{xh}")
        for d in muc_khac:
            ghi_chu = f" ({esc(d['ghi_chu'])})" if d.get("ghi_chu") else ""
            dong.append(f"• {esc(d['ten'])}: <b>{so(d['gia'], 2)}%</b> {dau(d['thay_doi'], 2, ' điểm')}{ghi_chu}")
        dong.append("")

    tn = vm.get("trong_nuoc") or {}
    if tn.get("vcb") or tn.get("sjc"):
        dong.append("<b>🇻🇳 Trong nước</b>")
        if tn.get("vcb"):
            dong.append(f"• USD Vietcombank: mua {so(tn['vcb']['mua'], 0)} / bán {so(tn['vcb']['ban'], 0)}")
        if tn.get("sjc"):
            dong.append(f"• Vàng SJC: mua {so(tn['sjc']['mua'] / 1e6, 2)} / bán {so(tn['sjc']['ban'] / 1e6, 2)} triệu/lượng")
        if tn.get("vang_quy_doi"):
            dong.append(f"• Vàng thế giới quy đổi: {so(tn['vang_quy_doi'] / 1e6, 2)} triệu/lượng "
                        f"(SJC chênh {so(tn['chenh_lech_vang'], 1)}%)")
        dong.append("")

    if vm["loi"]:
        dong.append(f"<i>Chưa lấy được: {esc(', '.join(vm['loi']))}</i>")
    return "\n".join(dong).strip()


# ======================================================================
# ======================================================================
def ban_tin_dong_tien(ngay: str, chi_so: list[dict], cp: list[dict], co_ban: dict[str, dict],
                      bctc_moi: list[str], canh_bao_dm: list[str], loi: list[str], cfg: dict) -> str:
    """Bản tin cuối ngày: khối lượng bất thường, khối ngoại, mua/bán chủ động, lệnh lớn."""
    top = int((cfg.get("cap_nhat_15_phut") or {}).get("so_ma_top", 5))
    ngay_vn = datetime.fromisoformat(ngay).strftime("%d/%m/%Y")
    tang = sum(1 for k in cp if k["thay_doi_pct"] > 0)
    giam = sum(1 for k in cp if k["thay_doi_pct"] < 0)
    dong = [f"<b>📊 {esc(cfg.get('nhom_co_phieu', 'VN30'))} — dòng tiền phiên {ngay_vn}</b>"]
    for c in chi_so:
        dong.append(f"<b>{esc(c['ten'])}</b> {so(c['diem'], 2)} {dau(c['pct'])}")
    gt_tong = sum(k.get("gt") or 0 for k in cp)
    dong += [f"Tăng {tang} · Giảm {giam} · Đứng {len(cp) - tang - giam} · GTGD nhóm {so(gt_tong, 0)} tỷ", ""]

    def pct(k):
        return f"{'+' if k['thay_doi_pct'] > 0 else ''}{so(k['thay_doi_pct'], 1)}%"

    if canh_bao_dm:
        dong += ["<b>💼 Danh mục của bạn</b>"] + [esc(c) for c in canh_bao_dm] + [""]

    if bctc_moi:
        dong.append("<b>🆕 Báo cáo tài chính mới</b>")
        for ma in bctc_moi:
            cb = co_ban.get(ma, {})
            ct = []
            if cb.get("doanh_thu_yoy") is not None:
                ct.append(f"DT {'+' if cb['doanh_thu_yoy'] > 0 else ''}{so(cb['doanh_thu_yoy'], 0)}%")
            if cb.get("loi_nhuan_yoy") is not None:
                ct.append(f"LNST {'+' if cb['loi_nhuan_yoy'] > 0 else ''}{so(cb['loi_nhuan_yoy'], 0)}%")
            if cb.get("roe") is not None:
                ct.append(f"ROE {so(cb['roe'], 1)}%")
            dg = "✅ đạt tiêu chí" if cb.get("dat_chuan") else ("⚠️ " + "; ".join(cb["xau"][:2]) if cb.get("xau") else "")
            dong.append(f"• <b>{esc(ma)}</b> {esc(cb.get('ky_moi_nhat', ''))}: {esc(', '.join(ct))} (so cùng kỳ) {esc(dg)}")
        dong.append("")

    kl = sorted([k for k in cp if (k.get("ty_le_kl") or 0) >= 1.5], key=lambda k: -k["ty_le_kl"])[:10]
    if kl:
        dong.append("<b>🔊 Khối lượng bất thường</b> (so với TB 20 phiên)")
        for k in kl:
            dong.append(f"• <b>{esc(k['ma'])}</b> ×{so(k['ty_le_kl'], 1)} · {so(k.get('gt') or 0, 0)} tỷ · giá {pct(k)}")
        dong.append("")

    nn = [k for k in cp if k.get("nn_rong") is not None]
    if nn:
        tong = sum(k["nn_rong"] for k in nn)
        dong.append(f"<b>🌍 Khối ngoại {'mua' if tong >= 0 else 'bán'} ròng {so(abs(tong), 1)} tỷ</b>")
        mua = sorted([k for k in nn if k["nn_rong"] > 0], key=lambda k: -k["nn_rong"])[:top]
        ban = sorted([k for k in nn if k["nn_rong"] < 0], key=lambda k: k["nn_rong"])[:top]
        if mua:
            dong.append("Mua ròng: " + ", ".join(f"<b>{esc(k['ma'])}</b> {so(k['nn_rong'], 1)}" for k in mua))
        if ban:
            dong.append("Bán ròng: " + ", ".join(f"<b>{esc(k['ma'])}</b> {so(-k['nn_rong'], 1)}" for k in ban))
        dong.append("")

    cd = [k for k in cp if k.get("lenh") and k["lenh"]["mua"] + k["lenh"]["ban"] > 0]
    if cd:
        for k in cd:
            k["_rong_cd"] = k["lenh"]["mua"] - k["lenh"]["ban"]
        dong.append("<b>🐋 Mua/bán chủ động</b> (ròng, tỷ đồng)")
        mua = sorted([k for k in cd if k["_rong_cd"] >= 1 and k["lenh"]["ti_le_mua"] >= 55],
                     key=lambda k: -k["_rong_cd"])[:top]
        ban = sorted([k for k in cd if k["_rong_cd"] <= -1 and k["lenh"]["ti_le_mua"] <= 45],
                     key=lambda k: k["_rong_cd"])[:top]
        if mua:
            dong.append("Mua chủ động: " + ", ".join(
                f"<b>{esc(k['ma'])}</b> +{so(k['_rong_cd'], 1)} ({so(k['lenh']['ti_le_mua'], 0)}%)" for k in mua))
        if ban:
            dong.append("Bán chủ động: " + ", ".join(
                f"<b>{esc(k['ma'])}</b> {so(k['_rong_cd'], 1)} ({so(100 - k['lenh']['ti_le_mua'], 0)}%)" for k in ban))
        lon = sorted([(k["ma"], l) for k in cd for l in k["lenh"]["lenh_lon"]], key=lambda x: -x[1]["gt"])[:top]
        if lon:
            from .dong_tien import mo_ta_lenh
            dong.append("Lệnh lớn nhất: " + "; ".join(f"<b>{esc(ma)}</b> {esc(mo_ta_lenh(l))}" for ma, l in lon))
        dong.append("")

    xep = sorted(cp, key=lambda k: -k["thay_doi_pct"])
    dong.append("▲ " + ", ".join(f"{k['ma']} {pct(k)}" for k in xep[:top] if k["thay_doi_pct"] > 0))
    dong.append("▼ " + ", ".join(f"{k['ma']} {pct(k)}" for k in xep[::-1][:top] if k["thay_doi_pct"] < 0))
    dong.append("")

    dat = sorted(m for m, c in co_ban.items() if c.get("dat_chuan"))
    if dat:
        dong.append(f"<b>⭐ Đạt tiêu chí cơ bản</b> (LNST +≥{cfg['co_ban']['loi_nhuan_tang_yoy']}% cùng kỳ, "
                    f"ROE ≥{cfg['co_ban']['roe_toi_thieu']}%): {esc(', '.join(dat))}")
        dong.append("")
    if loi:
        dong.append(f"<i>Không lấy được dữ liệu: {esc(', '.join(loi))}</i>")
    dong.append("<i>Giá theo nghìn đồng, giá trị theo tỷ đồng. Mua/bán chủ động tính theo chiều khớp lệnh. "
                "Chỉ là công cụ hỗ trợ, không phải khuyến nghị đầu tư.</i>")
    return "\n".join(d for d in dong if d.strip() not in ("▲", "▼")).strip()
