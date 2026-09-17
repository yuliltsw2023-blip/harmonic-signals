#!/usr/bin/env python3
"""M15 scalping scanner (universe SCALP_SYMBOLS, lihat config/pairs.py).
Dijalankan GitHub Actions tiap 15 menit di sesi London/NY — cron-nya
sengaja NONAKTIF di repo private (lihat .github/workflows/scan-m15.yml)."""

import os
import sys

import _bootstrap  # noqa: F401
from lib.scanner import run_scan

if __name__ == "__main__":
    sys.exit(run_scan(os.environ.get("SCALP_TIMEFRAME", "M15").strip().upper() or "M15"))
