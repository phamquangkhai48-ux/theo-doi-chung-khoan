"""
Quét trong phiên: chạy mỗi phút (chế độ liên tục) hoặc mỗi 15 phút.

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

from . import dong_tien as dt
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


# ---------------------------------------------------------------- nền so sánh
def nen_so_sanh(ds: list[str], tt: dict, hom_nay: str) -> tuple[dict, str | None]:
    """
    Khối lượng & giá trị trung bình 20 phiên trước (không tính hôm nay), lấy 1 lần/ngày.
    Trả về ({mã: {"kl": .., "gt": .., "gia_truoc": ..}}, ngày có dữ liệu mới nhất).
    """
    cache = tt.get("nen") or {}
    if cache.get("ngay") == hom_nay and cache.get("du_lieu"):
        return cache["du_lieu"], cache.get("ngay_moi")
    gia = nd.lay_gia_nhieu_ma(ds, so_ngay=60)
    kq, ngay_moi = {}, None
    for ma, (df, _) in gia.items():
        ngay_cuoi = df.index[-1].date().isoformat()
        ngay_moi = max(ngay_moi or ngay_cuoi, ngay_cuoi)
        cu = df[df.index.date.astype(str) < hom_nay] if ngay_cuoi == hom_nay else df
        cu = cu.tail(20)
        if len(cu) < 5:
            continue
        kq[ma] = {"kl": float(cu["volume"].mean()),
                  "gt": float((cu["volume"] * cu["close"]).mean() / 1e6),
                  "gia_truoc": float(cu["close"].iloc[-1])}
    tt["nen"] = {"ngay": hom_nay, "ngay_moi": ngay_moi, "du_lieu": kq}
    return kq, ngay_moi


# ---------------------------------------------------------------- cổ phiếu VN
def quet_co_phieu(ds: list[str], cfg: dict, bay_gio: datetime, tt: dict,
                  canh_bao: list[str], hom_nay: str) -> dict | None:
    c15, cdt = cfg["cap_nhat_15_phut"], cfg["dong_tien"]
    nen, ngay_moi = nen_so_sanh(ds, tt, hom_nay)
    bang, nguon_bang = dt.lay_bang_gia(ds)
    if not bang:
        log.warning("Không lấy được bảng giá")
        return None
    # Ngày nghỉ: khối lượng toàn nhóm = 0, hoặc dữ liệu ngày gần nhất không phải hôm nay
    if sum(b["kl"] for b in bang.values()) == 0 or (ngay_moi and ngay_moi < hom_nay and bay_gio.hour >= 10):
        log.info("Hôm nay không có phiên — bỏ qua cổ phiếu")
        return None

    ty_le = ty_le_phien_vn(bay_gio)
    da_bao = tt.setdefault("da_bao", {})
    # Mốc so sánh ngắn hạn: ảnh chụp bảng giá gần nhất cách đây ít nhất `cua_so_phut` phút
    cua_so = float(cdt.get("cua_so_phut", 5))
    luc_nay = bay_gio.replace(tzinfo=None)
    anh_list = [a for a in tt.get("anh", []) if a.get("_ngay") == hom_nay]
    du_xa = [a for a in anh_list if (luc_nay - datetime.fromisoformat(a["_luc"])).total_seconds() >= cua_so * 60 - 20]
    truoc_all = du_xa[-1] if du_xa else {}
    ty_le_truoc = truoc_all.get("_ty_le")
    tu_luc = datetime.fromisoformat(truoc_all["_luc"]) if truoc_all else None
    phut = round((luc_nay - tu_luc).total_seconds() / 60) if tu_luc else None
    danh_muc = {str(x["ma"]).upper(): x for x in (cfg.get("danh_muc") or [])}
    slot = f"{bay_gio.hour}{bay_gio.minute // 15}"          # mỗi mã báo tối đa 1 lần / 15 phút / loại
    kq, ung_vien = [], []
    GT_TOI_THIEU = float(cdt.get("gia_tri_cua_so_toi_thieu_ty", cdt.get("gia_tri_15_phut_toi_thieu_ty", 3)))

    for ma in ds:
        b = bang.get(ma)
        if not b:
            continue
        n = nen.get(ma, {})
        kl_tb, gt_tb = n.get("kl"), n.get("gt")
        r = {"ma": ma, "gia": b["gia"], "thay_doi_pct": b["pct"], "kl": b["kl"], "gt": b["gt"],
             "ty_le_kl": (b["kl"] / (kl_tb * max(ty_le, 0.15))) if kl_tb else None,
             "nn_rong": dt.gt_ty(b["gia"], b["nn_mua"] - b["nn_ban"]) if b["co_nn"] else None,
             "nn_mua": dt.gt_ty(b["gia"], b["nn_mua"]), "nn_ban": dt.gt_ty(b["gia"], b["nn_ban"]),
             "gt_tb": gt_tb}
        kq.append(r)
        moi: list[tuple[str, int]] = []

        def them(khoa: str, noi_dung: str, diem: int):
            if khoa not in da_bao:
                da_bao[khoa] = hom_nay
                moi.append((noi_dung, diem))

        huong = 1 if b["pct"] > 0 else -1 if b["pct"] < 0 else 0
        # 1) Khối lượng cả ngày bất thường (so với TB 20 phiên, quy đổi theo thời gian đã giao dịch)
        if r["ty_le_kl"] and ty_le >= 0.3:
            muc = [m for m in cdt.get("kl_dot_bien_ngay", [2, 3, 5]) if r["ty_le_kl"] >= m]
            if muc:
                them(f"{hom_nay}|{ma}|klngay|{muc[-1]}",
                     f"KL gấp {so(r['ty_le_kl'], 1)} lần TB20 (quy đổi cả phiên)", huong)
        # 2) Khối lượng dồn dập trong vài phút vừa qua
        tr = (truoc_all or {}).get(ma)
        if tr and kl_tb and ty_le_truoc is not None:
            them_kl = b["kl"] - tr["kl"]
            phan = max(ty_le - ty_le_truoc, 0.03)
            r["ty_le_15"] = them_kl / (kl_tb * phan)
            r["gt_15"] = dt.gt_ty(b["gia"], them_kl)
            if (r["ty_le_15"] >= float(cdt.get("kl_dot_bien_cua_so", cdt.get("kl_dot_bien_15_phut", 5)))
                    and r["gt_15"] >= GT_TOI_THIEU):
                them(f"{hom_nay}|{ma}|kl15|{slot}",
                     f"{phut} phút qua khớp {so(r['gt_15'], 1)} tỷ, gấp {so(r['ty_le_15'], 1)} lần nhịp bình thường",
                     huong)
                ung_vien.append(ma)
            # Khối ngoại dồn dập trong vài phút
            if b["co_nn"] and "nn_mua" in tr:
                nn15 = dt.gt_ty(b["gia"], (b["nn_mua"] - tr["nn_mua"]) - (b["nn_ban"] - tr["nn_ban"]))
                if abs(nn15) >= float(cdt.get("khoi_ngoai_cua_so_ty", cdt.get("khoi_ngoai_15_phut_ty", 10))):
                    them(f"{hom_nay}|{ma}|nn15|{slot}",
                         f"khối ngoại {'mua' if nn15 > 0 else 'bán'} ròng {so(abs(nn15), 1)} tỷ trong {phut} phút",
                         1 if nn15 > 0 else -1)
        # 3) Khối ngoại mua/bán ròng lũy kế trong ngày
        if r["nn_rong"] is not None:
            muc = [m for m in cdt.get("khoi_ngoai_rong_ty", [20, 50, 100, 200]) if abs(r["nn_rong"]) >= m]
            if muc:
                them(f"{hom_nay}|{ma}|nn|{'+' if r['nn_rong'] > 0 else '-'}{muc[-1]}",
                     f"khối ngoại {'mua' if r['nn_rong'] > 0 else 'bán'} ròng {so(abs(r['nn_rong']), 1)} tỷ "
                     f"(mua {so(r['nn_mua'], 1)} / bán {so(r['nn_ban'], 1)})", 1 if r["nn_rong"] > 0 else -1)
        # 4) Biến động giá mạnh, sát trần/sàn
        pct = b["pct"]
        buoc = float(c15.get("buoc_bien_dong_co_phieu", 3))
        nac = int(abs(pct) // buoc)
        if abs(pct) >= float(c15.get("tran_san", 6.5)):
            them(f"{hom_nay}|{ma}|transan|{'+' if pct > 0 else '-'}",
                 "sát giá trần" if pct > 0 else "sát giá sàn", 2 if pct > 0 else -2)
        elif nac >= 1:
            them(f"{hom_nay}|{ma}|bd|{'+' if pct > 0 else '-'}{nac}",
                 f"{'tăng' if pct > 0 else 'giảm'} quá {so(nac * buoc, 0)}% trong phiên", huong)

        r["_moi"] = moi
        if moi and ma not in ung_vien and any("KL" in m or "khớp" in m for m, _ in moi):
            ung_vien.append(ma)
        if ma in danh_muc:
            dm = ky_thuat.kiem_tra_danh_muc({**danh_muc[ma], "ma": ma}, b["gia"])
            if dm and f"{hom_nay}|{ma}|danhmuc|{dm[:2]}" not in da_bao:
                da_bao[f"{hom_nay}|{ma}|danhmuc|{dm[:2]}"] = hom_nay
                canh_bao.append(esc(dm))

    # 5) Soi lệnh mua/bán chủ động cho các mã có dòng tiền bất thường
    so_soi = int(cdt.get("so_ma_soi_lenh", 10))
    them_uv = sorted([r for r in kq if r.get("ty_le_15") and r["ma"] not in ung_vien
                      and r.get("gt_15", 0) >= GT_TOI_THIEU / 2 and r["ty_le_15"] >= 2],
                     key=lambda r: -r["ty_le_15"])
    ung_vien = (ung_vien + [r["ma"] for r in them_uv])[:so_soi]
    tim = {r["ma"]: r for r in kq}
    for ma in ung_vien:
        r = tim[ma]
        khop = dt.lay_khop_lenh(ma)
        if khop is None:
            continue
        pt = dt.phan_tich_lenh(khop, dt.nguong_lenh_lon(cdt, r.get("gt_tb")), tu=tu_luc)
        r["lenh"] = pt
        moi = r["_moi"]
        nguong_tl = float(cdt.get("mua_ban_chu_dong_ty_le", 70))
        if pt["ti_le_mua"] is not None and pt["mua"] + pt["ban"] >= float(cdt.get("mua_ban_chu_dong_toi_thieu_ty", 5)):
            khoang = f"{phut} phút qua" if tu_luc else "từ đầu phiên"
            if pt["ti_le_mua"] >= nguong_tl and f"{hom_nay}|{ma}|cd+|{slot}" not in da_bao:
                da_bao[f"{hom_nay}|{ma}|cd+|{slot}"] = hom_nay
                moi.append((f"MUA chủ động áp đảo {so(pt['ti_le_mua'], 0)}% {khoang} "
                            f"(mua {so(pt['mua'], 1)} / bán {so(pt['ban'], 1)} tỷ)", 2))
            elif pt["ti_le_mua"] <= 100 - nguong_tl and f"{hom_nay}|{ma}|cd-|{slot}" not in da_bao:
                da_bao[f"{hom_nay}|{ma}|cd-|{slot}"] = hom_nay
                moi.append((f"BÁN chủ động áp đảo {so(100 - pt['ti_le_mua'], 0)}% {khoang} "
                            f"(bán {so(pt['ban'], 1)} / mua {so(pt['mua'], 1)} tỷ)", -2))
        # Lệnh lớn: chỉ báo những lệnh chưa báo
        lon_moi = []
        for l in pt["lenh_lon"]:
            khoa = f"{hom_nay}|{ma}|lon|{l['time']}|{l['kl']}"
            if khoa not in da_bao:
                da_bao[khoa] = hom_nay
                lon_moi.append(l)
        if lon_moi:
            mua_l = sum(l["gt"] for l in lon_moi if l["chieu"] == "mua")
            ban_l = sum(l["gt"] for l in lon_moi if l["chieu"] == "ban")
            mo_ta = "; ".join(dt.mo_ta_lenh(l) for l in lon_moi[:3])
            moi.append((f"lệnh lớn: {mo_ta}", 1 if mua_l > ban_l else -1 if ban_l > mua_l else 0))

    for r in kq:
        moi = r.pop("_moi", [])
        if moi:
            tong = sum(d for _, d in moi)
            mui = "🟢" if tong > 0 else "🔴" if tong < 0 else "⚪"
            pct = r["thay_doi_pct"]
            canh_bao.append(f"{mui} <b>{esc(r['ma'])}</b> {so(r['gia'], 2)} ({'+' if pct > 0 else ''}{so(pct, 1)}%): "
                            + "; ".join(esc(m) for m, _ in moi))

    # Lưu ảnh chụp bảng giá lần này để các lần sau so sánh (giữ ~30 phút gần nhất)
    anh_list.append({"_ngay": hom_nay, "_ty_le": ty_le, "_luc": luc_nay.isoformat(),
                     **{ma: {"kl": b["kl"], "nn_mua": b["nn_mua"], "nn_ban": b["nn_ban"]} for ma, b in bang.items()}})
    tt["anh"] = [a for a in anh_list if (luc_nay - datetime.fromisoformat(a["_luc"])).total_seconds() <= 1800]
    tt.pop("truoc", None)
    log.info("Bảng giá %s: %d mã; soi lệnh %d mã", nguon_bang, len(bang), len(ung_vien))

    def bao(khoa: str, noi_dung: str):
        if khoa not in da_bao:
            da_bao[khoa] = hom_nay
            canh_bao.append(noi_dung)

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
                kl = sorted([k for k in cp if k.get("ty_le_kl") and k["ty_le_kl"] >= 1.5],
                            key=lambda k: -k["ty_le_kl"])[:so_top]
                if kl:
                    dong.append("🔊 KL đột biến: " + ", ".join(f"{k['ma']} ×{so(k['ty_le_kl'], 1)}" for k in kl))
                nn = [k for k in cp if k.get("nn_rong") is not None]
                if nn:
                    tong_nn = sum(k["nn_rong"] for k in nn)
                    mua = sorted([k for k in nn if k["nn_rong"] > 0], key=lambda k: -k["nn_rong"])[:so_top]
                    ban = sorted([k for k in nn if k["nn_rong"] < 0], key=lambda k: k["nn_rong"])[:so_top]
                    dong.append(f"🌍 Khối ngoại {'mua' if tong_nn >= 0 else 'bán'} ròng {so(abs(tong_nn), 1)} tỷ")
                    if mua:
                        dong.append("   mua: " + ", ".join(f"{k['ma']} {so(k['nn_rong'], 1)}" for k in mua))
                    if ban:
                        dong.append("   bán: " + ", ".join(f"{k['ma']} {so(-k['nn_rong'], 1)}" for k in ban))
        dong += _dong_vi_mo(vm)
        dong.append("")
    if canh_bao:
        dong.append(f"<b>⚡ Cảnh báo mới — {gio}</b>")
        dong += canh_bao
    return "\n".join(d for d in dong if d.strip() not in ("▲", "▼")).strip()
