"""Gửi tin nhắn Telegram. Nếu chưa cài token thì in ra màn hình."""
from __future__ import annotations

import html
import logging
import os
import time

import requests

log = logging.getLogger("telegram")
GIOI_HAN = 3900  # Telegram cho tối đa 4096 ký tự / tin


def esc(s) -> str:
    return html.escape(str(s), quote=False)


def _chia_nho(van_ban: str) -> list[str]:
    phan, hien_tai = [], ""
    for dong in van_ban.split("\n"):
        if len(hien_tai) + len(dong) + 1 > GIOI_HAN:
            phan.append(hien_tai)
            hien_tai = ""
        hien_tai += dong + "\n"
    if hien_tai.strip():
        phan.append(hien_tai)
    return phan


def gui(van_ban: str) -> bool:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        print("=" * 60)
        print("(Chưa cài TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID — in ra màn hình)")
        print(van_ban)
        return False
    ok = True
    for phan in _chia_nho(van_ban):
        for lan in range(3):
            try:
                r = requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                                  data={"chat_id": chat_id, "text": phan, "parse_mode": "HTML",
                                        "disable_web_page_preview": "true"}, timeout=30)
                if r.ok:
                    break
                log.warning("Telegram trả lỗi %s: %s", r.status_code, r.text[:300])
                if r.status_code == 400:  # lỗi định dạng -> gửi dạng chữ thường
                    requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                                  data={"chat_id": chat_id, "text": phan}, timeout=30)
                    break
            except Exception as e:  # noqa: BLE001
                log.warning("Gửi Telegram lỗi: %s", e)
            time.sleep(2)
        else:
            ok = False
        time.sleep(1)
    return ok
