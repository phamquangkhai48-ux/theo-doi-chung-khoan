"""
Cập nhật 15 phút một lần.

- Trong phiên Việt Nam (9:00–15:00): quét giá cổ phiếu + chỉ số VN + chỉ số thế giới,
  chỉ nhắn những cảnh báo MỚI (chưa báo trong ngày). Mỗi giờ gửi thêm một bản tóm tắt ngắn.
- Trong phiên Mỹ (20:00–4:15 sáng giờ VN): chỉ quét chỉ số thế giới, hàng hóa, tiền tệ.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta
from pathlib import Path

from . import ky_thuat
from . import nguon_du_lieu as nd
from .bao_cao import CO, TEN_NHOM, dau, so
from .thong_bao import esc

log = logging.getLogger("nhanh")
CHI_SO_VN = [("VNINDEX", "VN-Index"), ("VN30", "VN30"), ("HNXIndex", "HNX-Index")]


# ---------------------------------------------------------------- thời gian
def phien_hien_tai(bay_gio: datetime) -> str | None:
    """'vn', 'my' hoặc None. bay_gio là giờ Việt Nam."""
    thu, phut = bay_gio.weekday(), bay_gio.hour * 60 + bay_gio.minute
    if thu < 5 and 9 * 60 <= phut <= 15 * 60 + 5:
        return "vn"
    if thu < 5 and phut >= 20 * 60:                 # tối thứ 2 → thứ 6
        return "my"
    if 1 <= thu <= 5 and phut <= 4 * 60 + 15:       # rạng sáng thứ 3 → thứ 7
        return "my"
    return None


def ty_le_phien_vn(bay_gio: datetime) -> float:
    """Phần phiên VN đã trôi qua (9:00–11:30 và 13:00–14:45, tổng 255 phút)."""
    p = bay_gio.hour * 60 + bay_gio.minute
    sang = min(max(p - 9 * 60, 0), 150)
    chieu = min(max(p - 13 * 60, 0), 105)
    return max(min((sang + chieu) / 255, 1.0), 0.05)


# ---------------------------------------------------------------- trạng thái
def doc_tt(file: Path) -> dict:
    try:
        return json.loads(file.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def ghi_tt(file: Path, tt: dict, hom_nay: str):
    han = (datetime.fromisoformat(hom_nay) - timedelta(days=3)).date().isoformat()
    tt["da_bao"] = {k: v for k, v in tt.get("da_bao", {}).items() if v >= han}
    file.parent.mkdir(exist_ok=True)
    file.write_text(json.dumps(tt, ensure_ascii=False, indent=0), encoding="utf-8")


def _khoa_on_dinh(ten: str) -> str:
    """'RSI 72: quá mua' -> 'RSI : quá mua' (bỏ số để không báo lặp khi số thay đổi)."""
    return re.sub(r"[\d.,]+", "", ten).strip()


# ---------------------------------------------------------------- cổ phiếu VN
def quet_co_phieu(ds: list[str], cfg: dict, bay_gio: datetime, tt: dict,
                  canh_bao: list[str], hom_nay: str) -> dict | None:
    c15 = cfg["cap_nhat_15_phut"]
    gia = nd.lay_gia_nhieu_ma(ds, so_ngay=420)
    if not gia:
        log.warning("Không lấy được giá cổ phiếu nào")
        return None
    ngay_moi = max(df.index[-1] for df, _ in gia.values()).date().isoformat()
    if ngay_moi < hom_nay:
        log.info("Hôm nay chưa có phiên (dữ liệu mới nhất %s) — bỏ qua cổ phiếu", ngay_moi)
        return None

    ty_le = ty_le_phien_vn(bay_gio)
    da_bao = tt.setdefault("da_bao", {})
    danh_muc = {str(x["ma"]).upper(): x for x in (cfg.get("danh_muc") or [])}
    kq = []

    def bao(khoa: str, noi_dung: str):
        if khoa not in da_bao:
            da_bao[khoa] = hom_nay
            canh_bao.append(noi_dung)

    for ma in ds:
        if ma not in gia:
            continue
        df, _ = gia[ma]
        if df.index[-1].date().isoformat() != hom_nay:
            continue
        try:
            kt = ky_thuat.phan_tich(ma, df, cfg["ky_thuat"], ty_le_phien=ty_le)
        except Exception as e:  # noqa: BLE001
            log.debug("%s lỗi: %s", ma, e)
            continue
        kq.append(kt)
        moi: list[tuple[str, int]] = []          # (nội dung, điểm) các cảnh báo mới của mã này

        def them(khoa: str, noi_dung: str, diem: int):
            if khoa not in da_bao:
                da_bao[khoa] = hom_nay
                moi.append((noi_dung, diem))

        for ten, diem in kt["tin_hieu"]:
            # Đầu phiên khối lượng chưa đủ để so sánh -> bỏ tín hiệu khối lượng trước ~10:15
            if ten.startswith("Khối lượng") and ty_le < 0.3:
                continue
            them(f"{hom_nay}|{ma}|{_khoa_on_dinh(ten)}", ten, diem)

        pct = kt["thay_doi_pct"]
        buoc = float(c15.get("buoc_bien_dong_co_phieu", 3))
        nac = int(abs(pct) // buoc)
        if abs(pct) >= float(c15.get("tran_san", 6.5)):
            them(f"{hom_nay}|{ma}|transan|{'+' if pct > 0 else '-'}",
                 "sát giá trần" if pct > 0 else "sát giá sàn", 2 if pct > 0 else -2)
        elif nac >= 1:
            them(f"{hom_nay}|{ma}|bd|{'+' if pct > 0 else '-'}{nac}",
                 f"{'tăng' if pct > 0 else 'giảm'} quá {so(nac * buoc, 0)}% trong phiên", 1 if pct > 0 else -1)

        if moi:
            tong = sum(d for _, d in moi)
            mui = "🟢" if tong > 0 else "🔴" if tong < 0 else "⚪"
            gia_txt = f"{so(kt['gia'], 2)} ({'+' if pct > 0 else ''}{so(pct, 1)}%)"
            canh_bao.append(f"{mui} <b>{esc(ma)}</b> {gia_txt}: " + "; ".join(esc(n) for n, _ in moi))

        if ma in danh_muc:
            dm = ky_thuat.kiem_tra_danh_muc({**danh_muc[ma], "ma": ma}, kt["gia"])
            if dm:
                bao(f"{hom_nay}|{ma}|danhmuc|{dm[:2]}", esc(dm))

    # Chỉ số Việt Nam
    chi_so = []
    gia_cs = nd.lay_gia_nhieu_ma([m for m, _ in CHI_SO_VN], so_ngay=60, la_chi_so=True)
    buoc_cs = float(c15.get("buoc_bien_dong_chi_so_vn", 1.5))
    for ma, ten in CHI_SO_VN:
        if ma not in gia_cs:
            continue
        df, _ = gia_cs[ma]
        if df.index[-1].date().isoformat() != hom_nay or len(df) < 2:
            continue
        diem, truoc = df["close"].iloc[-1], df["close"].iloc[-2]
        pct = (diem / truoc - 1) * 100
        chi_so.append({"ten": ten, "diem": diem, "pct": pct, "doi": diem - truoc})
        nac = int(abs(pct) // buoc_cs)
        if nac >= 1:
            bao(f"{hom_nay}|{ma}|bd|{'+' if pct > 0 else '-'}{nac}",
                f"{'🟢' if pct > 0 else '🔴'} <b>{esc(ten)}</b> {so(diem, 2)} ({dau(pct)}): "
                f"{'tăng' if pct > 0 else 'giảm'} quá {so(nac * buoc_cs, 1)}%")
    return {"co_phieu": kq, "chi_so": chi_so, "ty_le": ty_le}


# ---------------------------------------------------------------- vĩ mô
def quet_vi_mo(cfg: dict, tt: dict, canh_bao: list[str], hom_nay: str) -> list[dict]:
    ds = cfg["vi_mo"]["chi_so"]
    du_lieu = nd.lay_yahoo([x["ma"] for x in ds], so_ngay=30)
    da_bao = tt.setdefault("da_bao", {})
    kq = []
    for x in ds:
        s = du_lieu.get(x["ma"])
        if s is None or len(s) < 2:
            continue
        la_ls = x.get("la_loi_suat", False)
        moi, cu = float(s.iloc[-1]), float(s.iloc[-2])
        d1 = (moi - cu) if la_ls else (moi / cu - 1) * 100
        ngay = s.index[-1].date().isoformat() if hasattr(s.index[-1], "date") else hom_nay
        kq.append({"ten": x["ten"], "nhom": x.get("nhom", ""), "gia": moi, "d1": d1, "la_loi_suat": la_ls})
        nguong = float(x.get("nguong_ngay", 999))
        nac = int(abs(d1) // nguong) if nguong > 0 else 0
        khoa = f"{ngay}|{x['ma']}|{'+' if d1 > 0 else '-'}{nac}"
        if nac >= 1 and khoa not in da_bao:
            da_bao[khoa] = hom_nay
            don_vi = " điểm %" if la_ls else "%"
            canh_bao.append(f"{'🟢' if d1 > 0 else '🔴'} <b>{esc(x['ten'])}</b> {so(moi, 2)}: "
                            f"{'+' if d1 > 0 else ''}{so(d1, 2)}{don_vi} so với phiên trước")
    return kq


# ---------------------------------------------------------------- soạn tin
def _dong_vi_mo(vm: list[dict]) -> list[str]:
    out = []
    for nhom in ["my", "chau_au", "chau_a", "tien_te", "hang_hoa", "loi_suat"]:
        muc = [c for c in vm if c["nhom"] == nhom]
        if not muc:
            continue
        phan = []
        for c in muc:
            if c["la_loi_suat"]:
                phan.append(f"{esc(c['ten'])} {so(c['gia'], 2)}% ({'+' if c['d1'] > 0 else ''}{so(c['d1'], 2)})")
            else:
                le = 0 if c["gia"] > 5000 else 2
                phan.append(f"{esc(c['ten'])} {so(c['gia'], le)} ({'+' if c['d1'] > 0 else ''}{so(c['d1'], 1)}%)")
        out.append(f"{CO.get(nhom, '•')} " + " · ".join(phan))
    return out


def soan_tin(bay_gio: datetime, phien: str, canh_bao: list[str], vn: dict | None,
             vm: list[dict], tom_tat: bool, so_top: int) -> str | None:
    if not canh_bao and not tom_tat:
        return None
    gio = bay_gio.strftime("%H:%M")
    dong = []
    if tom_tat:
        tieu_de = "🇻🇳 Trong phiên" if phien == "vn" else "🌙 Phiên Mỹ"
        dong.append(f"<b>{tieu_de} — {gio}</b>")
        if vn:
            for c in vn["chi_so"]:
                dong.append(f"<b>{esc(c['ten'])}</b> {so(c['diem'], 2)} {dau(c['pct'])} "
                            f"({'+' if c['doi'] > 0 else ''}{so(c['doi'], 2)} điểm)")
            cp = vn["co_phieu"]
            if cp:
                tang = sum(1 for k in cp if k["thay_doi_pct"] > 0)
                giam = sum(1 for k in cp if k["thay_doi_pct"] < 0)
                dong.append(f"Tăng {tang} · Giảm {giam} · Đứng {len(cp) - tang - giam}")
                xep = sorted(cp, key=lambda k: -k["thay_doi_pct"])
                dong.append("▲ " + ", ".join(f"{k['ma']} +{so(k['thay_doi_pct'], 1)}%"
                                             for k in xep[:so_top] if k["thay_doi_pct"] > 0))
                dong.append("▼ " + ", ".join(f"{k['ma']} {so(k['thay_doi_pct'], 1)}%"
                                             for k in xep[::-1][:so_top] if k["thay_doi_pct"] < 0))
                kl = sorted([k for k in cp if k.get("ty_le_kl")], key=lambda k: -k["ty_le_kl"])[:so_top]
                if kl:
                    dong.append("🔊 KL đột biến: " + ", ".join(f"{k['ma']} ×{so(k['ty_le_kl'], 1)}" for k in kl))
        dong += _dong_vi_mo(vm)
        dong.append("")
    if canh_bao:
        dong.append(f"<b>⚡ Cảnh báo mới — {gio}</b>")
        dong += canh_bao
    return "\n".join(d for d in dong if d.strip() not in ("▲", "▼")).strip()
