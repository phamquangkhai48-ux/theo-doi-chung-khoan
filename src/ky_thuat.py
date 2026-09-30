"""Tính chỉ báo kỹ thuật và chấm điểm tín hiệu cho từng cổ phiếu."""
from __future__ import annotations

import numpy as np
import pandas as pd

from .bao_cao import so


# ---------------------------------------------------------------- chỉ báo
def rsi(close: pd.Series, n: int = 14) -> pd.Series:
    """RSI theo cách tính Wilder (giống TradingView, AmiBroker)."""
    delta = close.diff()
    tang = delta.clip(lower=0)
    giam = -delta.clip(upper=0)
    tb_tang = tang.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    tb_giam = giam.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    rs = tb_tang / tb_giam.replace(0, np.nan)
    out = 100 - 100 / (1 + rs)
    return out.where(tb_giam != 0, 100.0)


def macd(close: pd.Series, nhanh=12, cham=26, tin_hieu=9):
    duong_macd = close.ewm(span=nhanh, adjust=False).mean() - close.ewm(span=cham, adjust=False).mean()
    duong_tin_hieu = duong_macd.ewm(span=tin_hieu, adjust=False).mean()
    return duong_macd, duong_tin_hieu


def them_chi_bao(df: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    df = df.copy()
    c = df["close"]
    df["ma_ngan"] = c.rolling(cfg["ma_ngan"]).mean()
    df["ma_trung"] = c.rolling(cfg["ma_trung"]).mean()
    df["ma_dai"] = c.rolling(cfg["ma_dai"]).mean()
    df["rsi"] = rsi(c, cfg["rsi_chu_ky"])
    df["macd"], df["macd_tin_hieu"] = macd(c)
    df["kl_tb20"] = df["volume"].rolling(20).mean()
    df["dinh_52t"] = df["high"].rolling(252, min_periods=120).max()
    df["day_52t"] = df["low"].rolling(252, min_periods=120).min()
    return df


# ---------------------------------------------------------------- tín hiệu
def _cat_len(a_nay, b_nay, a_truoc, b_truoc) -> bool:
    vals = [a_nay, b_nay, a_truoc, b_truoc]
    return all(pd.notna(v) for v in vals) and a_truoc <= b_truoc and a_nay > b_nay


def _cat_xuong(a_nay, b_nay, a_truoc, b_truoc) -> bool:
    vals = [a_nay, b_nay, a_truoc, b_truoc]
    return all(pd.notna(v) for v in vals) and a_truoc >= b_truoc and a_nay < b_nay


def phan_tich(ma: str, df_gia: pd.DataFrame, cfg: dict) -> dict:
    """Trả về dict gồm giá, % thay đổi, danh sách tín hiệu, tổng điểm, xu hướng."""
    df = them_chi_bao(df_gia, cfg)
    nay, truoc = df.iloc[-1], df.iloc[-2]
    d = cfg["diem"]
    tin_hieu: list[tuple[str, int]] = []

    def them(ten, khoa):
        tin_hieu.append((ten, d.get(khoa, 0)))

    n1, n2, n3 = cfg["ma_ngan"], cfg["ma_trung"], cfg["ma_dai"]

    if _cat_len(nay.close, nay.ma_ngan, truoc.close, truoc.ma_ngan):
        them(f"Giá cắt lên MA{n1}", "cat_len_ma_ngan")
    if _cat_xuong(nay.close, nay.ma_ngan, truoc.close, truoc.ma_ngan):
        them(f"Giá cắt xuống MA{n1}", "cat_xuong_ma_ngan")
    if _cat_len(nay.close, nay.ma_trung, truoc.close, truoc.ma_trung):
        them(f"Giá vượt MA{n2}", "vuot_ma_trung")
    if _cat_xuong(nay.close, nay.ma_trung, truoc.close, truoc.ma_trung):
        them(f"Giá thủng MA{n2}", "thung_ma_trung")
    if _cat_len(nay.ma_trung, nay.ma_dai, truoc.ma_trung, truoc.ma_dai):
        them(f"MA{n2} cắt lên MA{n3} (giao cắt vàng)", "giao_cat_vang")
    if _cat_xuong(nay.ma_trung, nay.ma_dai, truoc.ma_trung, truoc.ma_dai):
        them(f"MA{n2} cắt xuống MA{n3} (giao cắt tử thần)", "giao_cat_tu_than")

    if pd.notna(nay.rsi):
        if nay.rsi < cfg["rsi_qua_ban"]:
            them(f"RSI {nay.rsi:.0f}: quá bán", "rsi_qua_ban")
        elif nay.rsi > cfg["rsi_qua_mua"]:
            them(f"RSI {nay.rsi:.0f}: quá mua", "rsi_qua_mua")

    if _cat_len(nay.macd, nay.macd_tin_hieu, truoc.macd, truoc.macd_tin_hieu):
        them("MACD cắt lên đường tín hiệu", "macd_cat_len")
    if _cat_xuong(nay.macd, nay.macd_tin_hieu, truoc.macd, truoc.macd_tin_hieu):
        them("MACD cắt xuống đường tín hiệu", "macd_cat_xuong")

    if pd.notna(nay.kl_tb20) and nay.kl_tb20 > 0:
        ty_le_kl = nay.volume / nay.kl_tb20
        if ty_le_kl >= cfg["khoi_luong_dot_bien"]:
            if nay.close > truoc.close:
                them(f"Khối lượng gấp {so(ty_le_kl, 1)} lần TB20, giá tăng", "kl_dot_bien_tang")
            elif nay.close < truoc.close:
                them(f"Khối lượng gấp {so(ty_le_kl, 1)} lần TB20, giá giảm", "kl_dot_bien_giam")
    else:
        ty_le_kl = np.nan

    if pd.notna(truoc.dinh_52t) and nay.close > truoc.dinh_52t:
        them("Vượt đỉnh 52 tuần", "dinh_52_tuan")
    if pd.notna(truoc.day_52t) and nay.close < truoc.day_52t:
        them("Thủng đáy 52 tuần", "day_52_tuan")

    # Xu hướng tổng thể
    if all(pd.notna([nay.ma_trung, nay.ma_dai])):
        if nay.close > nay.ma_trung > nay.ma_dai:
            xu_huong = "tăng"
        elif nay.close < nay.ma_trung < nay.ma_dai:
            xu_huong = "giảm"
        else:
            xu_huong = "đi ngang"
    else:
        xu_huong = "chưa đủ dữ liệu"

    diem = sum(p for _, p in tin_hieu)
    return {
        "ma": ma,
        "ngay": df.index[-1].date().isoformat(),
        "gia": float(nay.close),
        "thay_doi_pct": float((nay.close / truoc.close - 1) * 100),
        "rsi": float(nay.rsi) if pd.notna(nay.rsi) else None,
        "ty_le_kl": float(ty_le_kl) if pd.notna(ty_le_kl) else None,
        "xu_huong": xu_huong,
        "tin_hieu": tin_hieu,
        "diem": diem,
    }


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
