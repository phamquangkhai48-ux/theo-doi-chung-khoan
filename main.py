"""
Chương trình chính.

Cách chạy:
    python main.py sang          # bản tin sáng: chỉ số thế giới sau khi Mỹ đóng cửa
    python main.py chieu         # bản tin chiều: dòng tiền VN100 + BCTC + vĩ mô trong nước
    python main.py chieu --bctc  # bắt buộc quét báo cáo tài chính hôm nay
    python main.py lien-tuc      # quét mỗi phút suốt một buổi giao dịch (cảnh báo tức thì)
    python main.py nhanh         # cập nhật 15 phút (cảnh báo mới + tóm tắt mỗi giờ)
    python main.py kiem-tra      # chẩn đoán: kiểm tra từng nguồn dữ liệu có hoạt động không
"""
from __future__ import annotations

import csv
import json
import logging
import os
import sys
import traceback
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

from src import bao_cao, co_ban, ky_thuat, nhanh, thong_bao, vi_mo
from src import dong_tien as dt
from src import nguon_du_lieu as nd

GOC = Path(__file__).resolve().parent
THU_MUC_DATA = GOC / "data"
FILE_TRANG_THAI = THU_MUC_DATA / "trang_thai.json"
GIO_VN = ZoneInfo("Asia/Ho_Chi_Minh")

logging.basicConfig(level=os.environ.get("MUC_LOG", "INFO"),
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("main")


def doc_cau_hinh() -> dict:
    with open(GOC / "config.yaml", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    # Danh mục cất trong GitHub Secret DANH_MUC (để không lộ khi kho để công khai)
    bi_mat = os.environ.get("DANH_MUC", "").strip()
    if bi_mat:
        try:
            dm = yaml.safe_load(bi_mat)
            if isinstance(dm, dict):
                dm = dm.get("danh_muc")
            if isinstance(dm, list):
                cfg["danh_muc"] = (cfg.get("danh_muc") or []) + dm
        except Exception as e:  # noqa: BLE001
            log.warning("Không đọc được secret DANH_MUC: %s", e)
    return cfg


def doc_trang_thai() -> dict:
    if FILE_TRANG_THAI.exists():
        try:
            return json.loads(FILE_TRANG_THAI.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            pass
    return {"ky_bctc": {}, "co_ban": {}}


def ghi_trang_thai(tt: dict):
    THU_MUC_DATA.mkdir(exist_ok=True)
    FILE_TRANG_THAI.write_text(json.dumps(tt, ensure_ascii=False, indent=1, default=str), encoding="utf-8")


def ghi_lich_su(ngay: str, ket_qua: list[dict]):
    """Lưu số liệu dòng tiền mỗi ngày vào data/lich_su_dong_tien.csv (mở được bằng Excel)."""
    THU_MUC_DATA.mkdir(exist_ok=True)
    file = THU_MUC_DATA / "lich_su_dong_tien.csv"
    moi = not file.exists()
    with open(file, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if moi:
            w.writerow(["ngay", "ma", "gia", "thay_doi_pct", "gtgd_ty", "kl_so_voi_tb20",
                        "khoi_ngoai_rong_ty", "mua_chu_dong_ty", "ban_chu_dong_ty", "so_lenh_lon"])
        for k in ket_qua:
            l = k.get("lenh") or {}
            r2 = lambda v: "" if v is None else round(v, 2)  # noqa: E731
            w.writerow([ngay, k["ma"], r2(k["gia"]), r2(k["thay_doi_pct"]), r2(k.get("gt")), r2(k.get("ty_le_kl")),
                        r2(k.get("nn_rong")), r2(l.get("mua")), r2(l.get("ban")), l.get("so_lenh_lon", "")])


def trong_mua_bao_cao(cfg: dict, hom_nay: datetime) -> bool:
    for m in cfg["co_ban"]["mua_bao_cao"]:
        if hom_nay.month == m["thang"] and m["tu_ngay"] <= hom_nay.day <= m["den_ngay"]:
            return True
    return hom_nay.weekday() == 0  # thứ Hai hằng tuần


def danh_sach_co_phieu(cfg: dict) -> list[str]:
    nhom = str(cfg.get("nhom_co_phieu", "VN30")).upper()
    ds = nd.lay_danh_sach_nhom(nhom)
    if ds:
        log.info("Lấy được danh sách %s tự động (%d mã)", nhom, len(ds))
    else:
        ds = [str(x).upper() for x in cfg["vn30_du_phong"]]
        log.warning("Không lấy được danh sách %s — dùng danh sách VN30 dự phòng", nhom)
    them = [str(x).upper() for x in (cfg.get("co_phieu_them") or [])]
    danh_muc = [str(x["ma"]).upper() for x in (cfg.get("danh_muc") or [])]
    return list(dict.fromkeys(ds + them + danh_muc))


# ======================================================================
def chay_sang(cfg: dict):
    vm = vi_mo.thu_thap(cfg, lay_trong_nuoc=False)
    thong_bao.gui(bao_cao.ban_tin_vi_mo(vm, "🌅 Bản tin sáng — thị trường thế giới"))


def chay_chieu(cfg: dict, ep_bctc: bool = False):
    hom_nay = datetime.now(GIO_VN)
    ngay = hom_nay.date().isoformat()
    theo_lich = os.environ.get("GITHUB_EVENT_NAME") == "schedule"
    tt = doc_trang_thai()
    ds = danh_sach_co_phieu(cfg)
    cdt = cfg["dong_tien"]
    ds_tai_chinh = {str(x).upper() for x in cfg.get("nganh_tai_chinh", [])}
    quet_bctc = ep_bctc or trong_mua_bao_cao(cfg, hom_nay)
    log.info("Theo dõi %d mã. Quét BCTC hôm nay: %s", len(ds), quet_bctc)

    # Nền so sánh (TB 20 phiên) + kiểm tra ngày nghỉ
    tam: dict = {}
    nen, ngay_moi = nhanh.nen_so_sanh(ds, tam, ngay)
    if theo_lich and ngay_moi and ngay_moi < ngay:
        log.info("Dữ liệu mới nhất là %s — hôm nay không có phiên, bỏ qua bản tin.", ngay_moi)
        return
    bang, nguon_bang = dt.lay_bang_gia(ds)
    log.info("Bảng giá %s: %d mã", nguon_bang or "không có", len(bang))

    ket_qua, loi, canh_bao_dm, bctc_moi = [], [], [], []
    ket_qua_cb: dict[str, dict] = dict(tt.get("co_ban", {}))
    danh_muc = {str(x["ma"]).upper(): x for x in (cfg.get("danh_muc") or [])}
    gia_du_phong = None if bang else nd.lay_gia_nhieu_ma(ds, so_ngay=60)

    for i, ma in enumerate(ds, 1):
        b = bang.get(ma)
        if b is None and gia_du_phong and ma in gia_du_phong:
            df = gia_du_phong[ma][0]
            if len(df) >= 2 and df.index[-1].date().isoformat() == ngay:
                c, t = df["close"].iloc[-1], df["close"].iloc[-2]
                b = {"gia": c, "pct": (c / t - 1) * 100, "kl": df["volume"].iloc[-1],
                     "gt": c * df["volume"].iloc[-1] / 1e6, "nn_mua": 0, "nn_ban": 0, "co_nn": False}
        if b is None:
            loi.append(ma)
            continue
        n = nen.get(ma, {})
        r = {"ma": ma, "gia": b["gia"], "thay_doi_pct": b["pct"], "kl": b["kl"], "gt": b["gt"],
             "ty_le_kl": b["kl"] / n["kl"] if n.get("kl") else None,
             "nn_rong": dt.gt_ty(b["gia"], b["nn_mua"] - b["nn_ban"]) if b["co_nn"] else None}
        khop = dt.lay_khop_lenh(ma)
        if khop is not None:
            r["lenh"] = dt.phan_tich_lenh(khop, dt.nguong_lenh_lon(cdt, n.get("gt")))
        ket_qua.append(r)
        if ma in danh_muc:
            cb_dm = ky_thuat.kiem_tra_danh_muc({**danh_muc[ma], "ma": ma}, b["gia"])
            if cb_dm:
                canh_bao_dm.append(cb_dm)

        if quet_bctc:
            try:
                cb = co_ban.phan_tich(ma, nd.lay_bctc(ma), cfg["co_ban"], ma in ds_tai_chinh)
                if cb.get("ky_moi_nhat"):
                    cu = tt.setdefault("ky_bctc", {}).get(ma)
                    if cu and cu != cb["ky_key"]:
                        bctc_moi.append(ma)
                    tt["ky_bctc"][ma] = cb["ky_key"]
                    ket_qua_cb[ma] = cb
            except Exception as e:  # noqa: BLE001
                log.error("%s: lỗi đọc BCTC: %s", ma, e)
                log.debug(traceback.format_exc())
        if i % 20 == 0:
            log.info("Đã xử lý %d/%d mã", i, len(ds))

    if not ket_qua:
        thong_bao.gui("⚠️ Hôm nay không lấy được dữ liệu cổ phiếu nào. "
                      "Hãy chạy mục 'Kiểm tra dữ liệu' trên GitHub để xem nguyên nhân.")
        return

    chi_so = []
    gia_cs = nd.lay_gia_nhieu_ma([m for m, _ in nhanh.CHI_SO_VN], so_ngay=60, la_chi_so=True)
    for ma, ten in nhanh.CHI_SO_VN:
        if ma in gia_cs and len(gia_cs[ma][0]) >= 2:
            df = gia_cs[ma][0]
            chi_so.append({"ten": ten, "diem": df["close"].iloc[-1],
                           "pct": (df["close"].iloc[-1] / df["close"].iloc[-2] - 1) * 100})

    tt["co_ban"] = ket_qua_cb
    ghi_trang_thai(tt)
    ghi_lich_su(ngay, ket_qua)
    thong_bao.gui(bao_cao.ban_tin_dong_tien(ngay, chi_so, ket_qua, ket_qua_cb, bctc_moi, canh_bao_dm, loi, cfg))

    vm = vi_mo.thu_thap(cfg, lay_trong_nuoc=True)
    thong_bao.gui(bao_cao.ban_tin_vi_mo(vm, "🌏 Vĩ mô cuối ngày"))


def chay_nhanh(cfg: dict):
    """Cập nhật 15 phút: chỉ báo cảnh báo mới; mỗi giờ thêm một bản tóm tắt."""
    c15 = cfg.get("cap_nhat_15_phut") or {}
    if not c15.get("bat", True):
        log.info("Cập nhật 15 phút đang tắt trong config.yaml")
        return
    bay_gio = datetime.now(GIO_VN)
    theo_lich = os.environ.get("GITHUB_EVENT_NAME") == "schedule"
    phien = nhanh.phien_hien_tai(bay_gio)
    if phien is None:
        if theo_lich:
            log.info("Ngoài giờ theo dõi — bỏ qua")
            return
        phien = "vn" if bay_gio.weekday() < 5 and 9 <= bay_gio.hour < 15 else "my"
    hom_nay = bay_gio.date().isoformat()
    file_tt = THU_MUC_DATA / "trang_thai_nhanh.json"
    tt = nhanh.doc_tt(file_tt)
    canh_bao: list[str] = []

    vn = None
    if phien == "vn" and c15.get("lien_tuc", True) and theo_lich:
        log.info("Trong phiên VN đã có chế độ quét liên tục — bỏ qua")
        return
    if phien == "vn":
        vn = nhanh.quet_co_phieu(danh_sach_co_phieu(cfg), cfg, bay_gio, tt, canh_bao, hom_nay)
        if vn is None and theo_lich:
            nhanh.ghi_tt(file_tt, tt, hom_nay)
            return                      # ngày nghỉ lễ
    vm = nhanh.quet_vi_mo(cfg, tt, canh_bao, hom_nay)

    khoa_gio = f"{hom_nay} {bay_gio.hour}"
    tom_tat = c15.get("tom_tat_moi_gio", True) and tt.get("tom_tat_gio") != khoa_gio
    if not theo_lich:
        tom_tat = True                   # chạy tay thì luôn gửi tóm tắt
    tin = nhanh.soan_tin(bay_gio, phien, canh_bao, vn, vm, tom_tat, int(c15.get("so_ma_top", 5)))
    if tin:
        thong_bao.gui(tin)
    if tom_tat:
        tt["tom_tat_gio"] = khoa_gio
    nhanh.ghi_tt(file_tt, tt, hom_nay)
    log.info("Xong: %d cảnh báo mới, tóm tắt: %s", len(canh_bao), tom_tat)


def chay_lien_tuc(cfg: dict):
    """
    Quét liên tục mỗi phút trong một buổi giao dịch (sáng 9:00–11:30 hoặc chiều 13:00–14:45).
    Cảnh báo dòng tiền gửi ngay khi phát hiện; vĩ mô 15 phút/lần; tóm tắt mỗi giờ.
    """
    import time as _t
    c15 = cfg.get("cap_nhat_15_phut") or {}
    chu_ky = max(30, int(c15.get("chu_ky_lien_tuc_giay", 60)))
    theo_lich = os.environ.get("GITHUB_EVENT_NAME") == "schedule"
    file_tt = THU_MUC_DATA / "trang_thai_nhanh.json"
    tt = nhanh.doc_tt(file_tt)
    ds = danh_sach_co_phieu(cfg)
    bat_dau = datetime.now(GIO_VN)
    buoi_sang = bat_dau.hour < 12
    ket_thuc = bat_dau.replace(hour=11 if buoi_sang else 14, minute=32 if buoi_sang else 47, second=0)
    log.info("Quét liên tục %d mã, mỗi %ds, đến %s", len(ds), chu_ky, ket_thuc.strftime("%H:%M"))
    lan_vi_mo, vm, lan = 0.0, [], 0

    while True:
        t0 = _t.time()
        bay_gio = datetime.now(GIO_VN)
        hom_nay = bay_gio.date().isoformat()
        p = bay_gio.hour * 60 + bay_gio.minute
        trong_gio = (9 * 60 + 14 <= p <= 11 * 60 + 31) or (13 * 60 <= p <= 14 * 60 + 46)
        canh_bao: list[str] = []
        vn = None
        if trong_gio or not theo_lich:
            try:
                vn = nhanh.quet_co_phieu(ds, cfg, bay_gio, tt, canh_bao, hom_nay)
            except Exception as e:  # noqa: BLE001
                log.error("Lỗi lần quét: %s", e)
                log.debug(traceback.format_exc())
            if vn is None and theo_lich and p >= 9 * 60 + 40:
                log.info("Không có phiên giao dịch — dừng")
                break
        if t0 - lan_vi_mo >= 15 * 60:
            try:
                vm = nhanh.quet_vi_mo(cfg, tt, canh_bao, hom_nay)
                lan_vi_mo = t0
            except Exception as e:  # noqa: BLE001
                log.error("Lỗi vĩ mô: %s", e)
        khoa_gio = f"{hom_nay} {bay_gio.hour}"
        tom_tat = bool(vn) and c15.get("tom_tat_moi_gio", True) and tt.get("tom_tat_gio") != khoa_gio
        if not theo_lich:
            tom_tat = True
        tin = nhanh.soan_tin(bay_gio, "vn", canh_bao, vn, vm, tom_tat, int(c15.get("so_ma_top", 5)))
        if tin:
            thong_bao.gui(tin)
        if tom_tat:
            tt["tom_tat_gio"] = khoa_gio
        nhanh.ghi_tt(file_tt, tt, hom_nay)
        lan += 1
        log.info("Lần %d (%s): %d cảnh báo mới, mất %.0fs", lan, bay_gio.strftime("%H:%M"),
                 len(canh_bao), _t.time() - t0)
        if not theo_lich or datetime.now(GIO_VN) >= ket_thuc:
            break
        _t.sleep(max(5, chu_ky - (_t.time() - t0)))


def chay_kiem_tra(cfg: dict):
    """Kiểm tra từng nguồn dữ liệu và gửi kết quả — dùng khi có lỗi."""
    import pandas as pd
    dong = ["<b>🔧 Kiểm tra nguồn dữ liệu</b>", ""]

    def ghi(ten, ok, chi_tiet=""):
        dong.append(f"{'✅' if ok else '❌'} {thong_bao.esc(ten)}{': ' + thong_bao.esc(chi_tiet) if chi_tiet else ''}")

    nhom = str(cfg.get("nhom_co_phieu", "VN30")).upper()
    vn30 = nd.lay_danh_sach_nhom(nhom)
    ghi(f"Danh sách {nhom} tự động", bool(vn30), f"{len(vn30)} mã" if vn30 else "sẽ dùng danh sách VN30 dự phòng")

    df, nguon = nd.lay_gia_co_phieu("FPT")
    ghi("Giá cổ phiếu (FPT)", df is not None,
        f"nguồn {nguon}, {len(df)} phiên, phiên cuối {df.index[-1].date()} giá {df['close'].iloc[-1]:.2f}" if df is not None else "")

    bang, nguon_bang = dt.lay_bang_gia(["FPT", "HPG", "VCB"])
    b = bang.get("FPT")
    ghi("Bảng giá (KL, khối ngoại)", bool(b),
        f"nguồn {nguon_bang}, FPT KL {b['kl']:,.0f}, NN mua {b['nn_mua']:,.0f} / bán {b['nn_ban']:,.0f}"
        + ("" if b["co_nn"] else " (không có số liệu khối ngoại)") if b else "")
    khop = dt.lay_khop_lenh("FPT")
    if khop is not None:
        pt = dt.phan_tich_lenh(khop, 2)
        ghi("Khớp lệnh mua/bán chủ động (FPT)", pt["mua"] + pt["ban"] > 0,
            f"{len(khop)} lệnh, mua CĐ {pt['mua']:.1f} tỷ / bán CĐ {pt['ban']:.1f} tỷ, {pt['so_lenh_lon']} lệnh ≥2 tỷ")
    else:
        ghi("Khớp lệnh mua/bán chủ động (FPT)", False, "ngoài giờ giao dịch có thể chưa có dữ liệu")

    bc = nd.lay_bctc("FPT")
    for ten, k in (("BCTC kết quả kinh doanh (FPT)", "kqkd"), ("Chỉ số tài chính (FPT)", "chi_so")):
        d = bc[k]
        ghi(ten, d is not None, f"{len(d)} quý, mới nhất Q{d.index[-1][1]}/{d.index[-1][0]}" if d is not None else "")
    cb = co_ban.phan_tich("FPT", bc, cfg["co_ban"], False)
    ghi("Đọc chỉ tiêu BCTC", cb.get("loi_nhuan_yoy") is not None,
        f"LNST cùng kỳ {cb.get('loi_nhuan_yoy'):+.1f}%, ROE {cb.get('roe')}" if cb.get("loi_nhuan_yoy") is not None
        else "không nhận ra cột lợi nhuận")
    if bc["kqkd"] is not None and cb.get("loi_nhuan_yoy") is None:
        dong.append("   Tên các cột: " + thong_bao.esc(", ".join(map(str, bc["kqkd"].columns[:25]))))

    y = nd.lay_yahoo(["^GSPC", "DX-Y.NYB", "BTC-USD"])
    ghi("Yahoo Finance (chỉ số thế giới)", len(y) == 3, f"{len(y)}/3 mã")
    for ten, ma in (("TradingView lợi suất 10N Việt Nam", "TVC:VN10Y"), ("TradingView lợi suất 10N Nhật", "TVC:JP10Y")):
        d = nd.lay_tradingview(ma)
        ghi(ten, d is not None, f"{d['gia']:.2f}%" if d else "")
    d = nd.lay_fred("IRLTLT01JPM156N")
    ghi("FRED (dự phòng lợi suất Nhật)", d is not None, f"{d['gia']:.2f}%" if d else "")
    d = nd.lay_ty_gia_vcb()
    ghi("Tỷ giá Vietcombank", d is not None, f"bán {d['ban']:,.0f}" if d else "")
    d = nd.lay_gia_vang_sjc()
    ghi("Giá vàng SJC", d is not None, f"bán {d['ban']:,.0f}" if d else "")

    dong += ["", f"Python {sys.version.split()[0]}, pandas {pd.__version__}"]
    thong_bao.gui("\n".join(dong))


# ======================================================================
def main():
    cfg = doc_cau_hinh()
    nd.NGHI_GIAY = float(cfg.get("nghi_giua_cac_lan_goi", 3.2))
    che_do = sys.argv[1] if len(sys.argv) > 1 else "chieu"
    try:
        if che_do == "sang":
            chay_sang(cfg)
        elif che_do == "chieu":
            chay_chieu(cfg, ep_bctc="--bctc" in sys.argv)
        elif che_do == "nhanh":
            chay_nhanh(cfg)
        elif che_do == "lien-tuc":
            chay_lien_tuc(cfg)
        elif che_do == "kiem-tra":
            chay_kiem_tra(cfg)
        else:
            print(__doc__)
    except Exception as e:  # noqa: BLE001
        log.error(traceback.format_exc())
        thong_bao.gui(f"⚠️ Chương trình gặp lỗi: {thong_bao.esc(str(e)[:500])}\n"
                      "Hãy chạy 'Kiểm tra dữ liệu' trên GitHub hoặc gửi ảnh chụp lỗi để được hỗ trợ.")
        raise


if __name__ == "__main__":
    main()
