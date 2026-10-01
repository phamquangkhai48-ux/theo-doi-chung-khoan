"""
Chương trình chính.

Cách chạy:
    python main.py sang          # bản tin sáng: chỉ số thế giới sau khi Mỹ đóng cửa
    python main.py chieu         # bản tin chiều: VN30 (kỹ thuật + BCTC) + vĩ mô trong nước
    python main.py chieu --bctc  # bắt buộc quét báo cáo tài chính hôm nay
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

from src import bao_cao, co_ban, ky_thuat, thong_bao, vi_mo
from src import nguon_du_lieu as nd

GOC = Path(__file__).resolve().parent
THU_MUC_DATA = GOC / "data"
FILE_TRANG_THAI = THU_MUC_DATA / "trang_thai.json"
FILE_LICH_SU = THU_MUC_DATA / "lich_su_tin_hieu.csv"
GIO_VN = ZoneInfo("Asia/Ho_Chi_Minh")

logging.basicConfig(level=os.environ.get("MUC_LOG", "INFO"),
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("main")


def doc_cau_hinh() -> dict:
    with open(GOC / "config.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


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


def ghi_lich_su(ket_qua: list[dict]):
    THU_MUC_DATA.mkdir(exist_ok=True)
    moi = not FILE_LICH_SU.exists()
    with open(FILE_LICH_SU, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if moi:
            w.writerow(["ngay", "ma", "gia", "thay_doi_pct", "diem", "xu_huong", "tin_hieu"])
        for k in ket_qua:
            if k["tin_hieu"]:
                w.writerow([k["ngay"], k["ma"], round(k["gia"], 2), round(k["thay_doi_pct"], 2),
                            k["diem"], k["xu_huong"], " | ".join(t for t, _ in k["tin_hieu"])])


def trong_mua_bao_cao(cfg: dict, hom_nay: datetime) -> bool:
    for m in cfg["co_ban"]["mua_bao_cao"]:
        if hom_nay.month == m["thang"] and m["tu_ngay"] <= hom_nay.day <= m["den_ngay"]:
            return True
    return hom_nay.weekday() == 0  # thứ Hai hằng tuần


def danh_sach_co_phieu(cfg: dict) -> list[str]:
    ds = nd.lay_danh_sach_vn30() if cfg.get("tu_dong_lay_vn30", True) else []
    if ds:
        log.info("Lấy được danh sách VN30 tự động: %s", ", ".join(ds))
    else:
        ds = [str(x).upper() for x in cfg["vn30_du_phong"]]
        log.info("Dùng danh sách VN30 dự phòng trong config.yaml")
    them = [str(x).upper() for x in (cfg.get("co_phieu_them") or [])]
    danh_muc = [str(x["ma"]).upper() for x in (cfg.get("danh_muc") or [])]
    return list(dict.fromkeys(ds + them + danh_muc))


# ======================================================================
def chay_sang(cfg: dict):
    vm = vi_mo.thu_thap(cfg, lay_trong_nuoc=False)
    thong_bao.gui(bao_cao.ban_tin_vi_mo(vm, "🌅 Bản tin sáng — thị trường thế giới"))


def chay_chieu(cfg: dict, ep_bctc: bool = False):
    hom_nay = datetime.now(GIO_VN)
    theo_lich = os.environ.get("GITHUB_EVENT_NAME") == "schedule"
    tt = doc_trang_thai()
    ds = danh_sach_co_phieu(cfg)
    ds_tai_chinh = {str(x).upper() for x in cfg.get("nganh_tai_chinh", [])}
    quet_bctc = ep_bctc or trong_mua_bao_cao(cfg, hom_nay)
    log.info("Theo dõi %d mã. Quét BCTC hôm nay: %s", len(ds), quet_bctc)

    ket_qua_kt, loi, nguon_dung = [], [], set()
    ket_qua_cb: dict[str, dict] = dict(tt.get("co_ban", {}))
    bctc_moi: list[str] = []
    canh_bao_dm: list[str] = []
    danh_muc = {str(x["ma"]).upper(): x for x in (cfg.get("danh_muc") or [])}

    for i, ma in enumerate(ds, 1):
        log.info("[%d/%d] %s", i, len(ds), ma)
        try:
            df, nguon = nd.lay_gia_co_phieu(ma)
            if df is None:
                loi.append(ma)
                continue
            nguon_dung.add(nguon)
            kt = ky_thuat.phan_tich(ma, df, cfg["ky_thuat"])
            ket_qua_kt.append(kt)
            if ma in danh_muc:
                cb_dm = ky_thuat.kiem_tra_danh_muc({**danh_muc[ma], "ma": ma}, kt["gia"])
                if cb_dm:
                    canh_bao_dm.append(cb_dm)
        except Exception as e:  # noqa: BLE001
            log.error("%s: lỗi phân tích kỹ thuật: %s", ma, e)
            log.debug(traceback.format_exc())
            loi.append(ma)
            continue

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

    if not ket_qua_kt:
        thong_bao.gui("⚠️ Hôm nay không lấy được dữ liệu cổ phiếu nào. "
                      "Hãy chạy mục 'Kiểm tra dữ liệu' trên GitHub để xem nguyên nhân.")
        return

    # Ngày nghỉ lễ: dữ liệu mới nhất không phải hôm nay -> không gửi bản tin (khi chạy tự động)
    ngay_du_lieu = max(k["ngay"] for k in ket_qua_kt)
    if theo_lich and ngay_du_lieu < hom_nay.date().isoformat():
        log.info("Dữ liệu mới nhất là %s — hôm nay không có phiên, bỏ qua bản tin.", ngay_du_lieu)
        return

    tt["co_ban"] = ket_qua_cb
    ghi_trang_thai(tt)
    ghi_lich_su(ket_qua_kt)

    if "yahoo" in nguon_dung:
        log.warning("Một số mã lấy giá từ Yahoo (dự phòng) do Vietcap không trả dữ liệu.")

    thong_bao.gui(bao_cao.ban_tin_co_phieu(ket_qua_kt, ket_qua_cb, bctc_moi, canh_bao_dm, loi, cfg,
                                           co_chay_bctc=bool(ket_qua_cb)))

    vm = vi_mo.thu_thap(cfg, lay_trong_nuoc=True)
    thong_bao.gui(bao_cao.ban_tin_vi_mo(vm, "🌏 Vĩ mô cuối ngày"))


def chay_kiem_tra(cfg: dict):
    """Kiểm tra từng nguồn dữ liệu và gửi kết quả — dùng khi có lỗi."""
    import pandas as pd
    dong = ["<b>🔧 Kiểm tra nguồn dữ liệu</b>", ""]

    def ghi(ten, ok, chi_tiet=""):
        dong.append(f"{'✅' if ok else '❌'} {thong_bao.esc(ten)}{': ' + thong_bao.esc(chi_tiet) if chi_tiet else ''}")

    vn30 = nd.lay_danh_sach_vn30()
    ghi("Danh sách VN30 tự động", bool(vn30), f"{len(vn30)} mã" if vn30 else "sẽ dùng danh sách dự phòng")

    df, nguon = nd.lay_gia_co_phieu("FPT")
    ghi("Giá cổ phiếu (FPT)", df is not None,
        f"nguồn {nguon}, {len(df)} phiên, phiên cuối {df.index[-1].date()} giá {df['close'].iloc[-1]:.2f}" if df is not None else "")

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
