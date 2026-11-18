"""Kirim pesan Telegram yang disiapkan run.py (GOLDNEWS_OUTBOX) setelah deploy."""

import os
import sys

from goldnews import telegram

path = os.environ.get("GOLDNEWS_OUTBOX", "")
if not path or not os.path.exists(path):
    print("Tidak ada pesan untuk dikirim.")
    sys.exit(0)
with open(path, encoding="utf-8") as f:
    telegram.send(f.read())
print("Terkirim ke Telegram.")
