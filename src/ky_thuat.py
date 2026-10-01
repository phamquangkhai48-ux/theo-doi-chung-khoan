"""Cảnh báo cắt lỗ / chốt lời cho danh mục đang nắm giữ."""
from __future__ import annotations

from .bao_cao import so


def kiem_tra_danh_muc(vi_the: dict, gia_hien_tai: float) -> str | None:
    """Cảnh báo cắt lỗ / chốt lời cho mã đang nắm giữ."""
    gia_mua = float(vi_the["gia_mua"])
    lai_lo = (gia_hien_tai / gia_mua - 1) * 100
    cat_lo = float(vi_the.get("cat_lo_phan_tram", 7))
    chot_loi = float(vi_the.get("chot_loi_phan_tram", 20))
    if lai_lo <= -cat_lo:
        return f"⛔ {vi_the['ma']}: lỗ {so(abs(lai_lo), 1)}% (giá {so(gia_hien_tai, 2)}) — chạm ngưỡng cắt lỗ {cat_lo:g}%"
    if lai_lo >= chot_loi:
        return f"💰 {vi_the['ma']}: lãi {so(lai_lo, 1)}% (giá {so(gia_hien_tai, 2)}) — đạt ngưỡng chốt lời {chot_loi:g}%"
    return None
