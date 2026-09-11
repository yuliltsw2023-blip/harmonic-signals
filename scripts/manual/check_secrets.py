#!/usr/bin/env python3
"""Print panjang + sha256[:8] tiap secret (bukan nilainya) untuk membandingkan
env di GitHub Actions vs lokal tanpa membocorkan isi."""

import hashlib
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _bootstrap_manual  # noqa: F401,E402

KEYS = ["TWELVEDATA_API_KEY", "ANTHROPIC_API_KEY", "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_CHAT_ID", "UPSTASH_REDIS_REST_URL", "UPSTASH_REDIS_REST_TOKEN"]

print(f"{'SECRET':26} {'len':>4} {'strip':>5}  fp")
for k in KEYS:
    raw = os.environ.get(k, "")
    s = raw.strip()
    fp = hashlib.sha256(s.encode()).hexdigest()[:8] if s else "-"
    print(f"{k:26} {len(raw):>4} {len(s):>5}  {fp}")
