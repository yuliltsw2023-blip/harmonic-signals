#!/usr/bin/env python3
"""Scan saham D1 (harmonic + POC pullback) — data Yahoo Finance, tanpa key.

python scripts/scan_stocks.py [us|idx|auto]

auto (default, dipakai cron): jam UTC < 15 → IDX (cron 09:15 UTC = 16:15 WIB,
setelah tutup bursa), selain itu → US (cron 21:15 UTC, setelah tutup NYSE).
"""

import sys
from datetime import datetime, timezone

import _bootstrap  # noqa: F401
from config.pairs import symbols_for
from lib.scanner import run_scan


def pick_market(arg: str) -> str:
    if arg in ("us", "idx"):
        return arg
    return "idx" if datetime.now(timezone.utc).hour < 15 else "us"


if __name__ == "__main__":
    market = pick_market(sys.argv[1].lower() if len(sys.argv) > 1 else "auto")
    print(f"[stocks] market={market}")
    sys.exit(run_scan("D1", pairs=symbols_for(f"STOCK_{market.upper()}")))
