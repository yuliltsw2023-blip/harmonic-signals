#!/usr/bin/env python3
"""Kirim pesan test ke Telegram. python scripts/manual/test_telegram.py"""

import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _bootstrap_manual  # noqa: F401,E402

from lib.telegram import send_message  # noqa: E402

msg = (f"<b>harmonic-signals</b> test ping\n"
       f"{datetime.now(timezone.utc).isoformat()} UTC\n"
       f"<i>kalau lo baca ini, bot & chat id sudah benar.</i>")
print(send_message(msg))
