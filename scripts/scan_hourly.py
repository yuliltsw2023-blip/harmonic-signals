#!/usr/bin/env python3
"""Satu job per jam (cron :01 UTC) yang menjalankan scan yang jatuh tempo:
H1 setiap jam, H4 di jam kelipatan 4, D1 di jam 00. Menggabungkan tiga
workflow jadi satu job = setup GitHub Actions dibayar sekali, dan H1 jalan
1 menit setelah candle close (dulu :20 + delay cron).

Manual: SCAN_FORCE=H4,D1 python scripts/scan_hourly.py"""

import os
import sys
from datetime import datetime, timezone

import _bootstrap  # noqa: F401
from lib.scanner import run_scan


def due_timeframes(hour: int) -> list[str]:
    tfs = ["H1"]
    if hour % 4 == 0:
        tfs.append("H4")
    if hour == 0:
        tfs.append("D1")
    return tfs


def main() -> int:
    forced = os.environ.get("SCAN_FORCE", "").strip()
    tfs = [t.strip().upper() for t in forced.split(",") if t.strip()] or due_timeframes(datetime.now(timezone.utc).hour)
    print(f"[hourly] {datetime.now(timezone.utc).isoformat()} → {tfs}")
    rc = 0
    for tf in tfs:
        rc = max(rc, run_scan(tf))
    return rc


if __name__ == "__main__":
    sys.exit(main())
