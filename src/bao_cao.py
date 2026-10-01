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
def _dong_co_phieu(kt: dict, cb: dict | None, chi_tiet=True) -> list[str]:
    sao = " ⭐" if cb and cb.get("dat_chuan") and kt["diem"] > 0 else ""
    dau_dong = (f"<b>{esc(kt['ma'])}</b>{sao} {so(kt['gia'], 2)} ({'+' if kt['thay_doi_pct'] > 0 else ''}"
                f"{so(kt['thay_doi_pct'], 1)}%) · điểm {kt['diem']:+d} · xu hướng {kt['xu_huong']}")
    out = [dau_dong]
    if chi_tiet:
        for ten, diem in kt["tin_hieu"]:
            out.append(f"   {'↑' if diem > 0 else '↓' if diem < 0 else '·'} {esc(ten)}")
        if cb and cb.get("ky_moi_nhat") and (cb["tot"] or cb["xau"]):
            tom_tat = "; ".join(cb["tot"][:3] + cb["xau"][:2])
            out.append(f"   📊 {esc(cb['ky_moi_nhat'])}: {esc(tom_tat)}")
    return out


def ban_tin_co_phieu(ky_thuat: list[dict], co_ban: dict[str, dict], bctc_moi: list[str],
                     canh_bao_danh_muc: list[str], loi: list[str], cfg: dict, co_chay_bctc: bool) -> str:
    kt_cfg = cfg["ky_thuat"]
    tich_cuc = sorted([k for k in ky_thuat if k["diem"] >= kt_cfg["nguong_tich_cuc"]], key=lambda k: -k["diem"])
    tieu_cuc = sorted([k for k in ky_thuat if k["diem"] <= kt_cfg["nguong_tieu_cuc"]], key=lambda k: k["diem"])
    khac = [k for k in ky_thuat if k not in tich_cuc and k not in tieu_cuc and k["diem"] != 0]

    ngay = ky_thuat[0]["ngay"] if ky_thuat else datetime.now(GIO_VN).date().isoformat()
    ngay_vn = datetime.fromisoformat(ngay).strftime("%d/%m/%Y")
    tang = sum(1 for k in ky_thuat if k["thay_doi_pct"] > 0)
    giam = sum(1 for k in ky_thuat if k["thay_doi_pct"] < 0)
    xh_tang = sum(1 for k in ky_thuat if k["xu_huong"] == "tăng")
    xh_giam = sum(1 for k in ky_thuat if k["xu_huong"] == "giảm")

    dong = [f"<b>📊 {esc(cfg.get('nhom_co_phieu', 'VN30'))} — phiên {ngay_vn}</b>",
            f"Tăng {tang} · Giảm {giam} · Đứng {len(ky_thuat) - tang - giam}  |  "
            f"Xu hướng tăng {xh_tang} mã · giảm {xh_giam} mã", ""]

    if canh_bao_danh_muc:
        dong.append("<b>💼 Danh mục của bạn</b>")
        dong += [esc(c) for c in canh_bao_danh_muc]
        dong.append("")

    if bctc_moi:
        dong.append("<b>🆕 Báo cáo tài chính mới</b>")
        for ma in bctc_moi:
            cb = co_ban.get(ma, {})
            chi_tiet = []
            if cb.get("doanh_thu_yoy") is not None:
                chi_tiet.append(f"DT {'+' if cb['doanh_thu_yoy'] > 0 else ''}{so(cb['doanh_thu_yoy'], 0)}%")
            if cb.get("loi_nhuan_yoy") is not None:
                chi_tiet.append(f"LNST {'+' if cb['loi_nhuan_yoy'] > 0 else ''}{so(cb['loi_nhuan_yoy'], 0)}%")
            if cb.get("roe") is not None:
                chi_tiet.append(f"ROE {so(cb['roe'], 1)}%")
            danh_gia = "✅ đạt tiêu chí" if cb.get("dat_chuan") else ("⚠️ " + "; ".join(cb["xau"][:2]) if cb.get("xau") else "")
            dong.append(f"• <b>{esc(ma)}</b> {esc(cb.get('ky_moi_nhat', ''))}: {esc(', '.join(chi_tiet))} (so cùng kỳ) {esc(danh_gia)}")
        dong.append("")

    if tich_cuc:
        dong.append("<b>🟢 Tín hiệu tích cực</b>")
        for k in tich_cuc:
            dong += _dong_co_phieu(k, co_ban.get(k["ma"]))
        dong.append("")
    if tieu_cuc:
        dong.append("<b>🔴 Tín hiệu tiêu cực</b>")
        for k in tieu_cuc:
            dong += _dong_co_phieu(k, co_ban.get(k["ma"]))
        dong.append("")
    if khac:
        dong.append("<b>⚪ Tín hiệu khác</b>")
        for k in khac:
            ds = ", ".join(t for t, _ in k["tin_hieu"])
            dong.append(f"• <b>{esc(k['ma'])}</b> {so(k['gia'], 2)}: {esc(ds)}")
        dong.append("")
    if not (tich_cuc or tieu_cuc or khac):
        dong += ["Hôm nay không có mã nào phát tín hiệu.", ""]

    # Bảng xếp hạng cơ bản (chỉ khi có chạy BCTC)
    if co_chay_bctc:
        dat = [m for m, cb in co_ban.items() if cb.get("dat_chuan")]
        if dat:
            dong.append(f"<b>⭐ Đạt tiêu chí cơ bản</b> (LNST +≥{cfg['co_ban']['loi_nhuan_tang_yoy']}% cùng kỳ, "
                        f"ROE ≥{cfg['co_ban']['roe_toi_thieu']}%): {esc(', '.join(sorted(dat)))}")
            dong.append("")

    if loi:
        dong.append(f"<i>Không lấy được dữ liệu: {esc(', '.join(loi))}</i>")
    dong.append("<i>⭐ = vừa có tín hiệu kỹ thuật tốt vừa đạt tiêu chí cơ bản. "
                "Giá theo nghìn đồng. Chỉ là công cụ hỗ trợ, không phải khuyến nghị đầu tư.</i>")
    return "\n".join(dong).strip()
