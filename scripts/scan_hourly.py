#!/usr/bin/env python3
"""Job terjadwal gabungan (cron tiap jam, Senin–Jumat) untuk H1 + H4 + D1.

GitHub Actions free tier TIDAK menjalankan cron tiap jam dengan andal: Sep 2026
hanya 4–5 run per hari di jam acak (04:39, 09:44, 14:33 …). Aturan lama "H4 kalau
jam % 4 == 0, D1 kalau jam == 0" membuat H4 ter-scan ±1×/hari dan D1 2× dalam 9 hari.
Sekarang jatuh tempo dihitung dari STATE: tiap run selalu scan H1, dan scan H4 / D1
kalau candle H4 / D1 terakhir yang sudah close belum pernah di-scan (key Upstash
`scan:last:H4` / `scan:last:D1`). Run yang terlambat otomatis mengejar.

Manual: SCAN_FORCE=H4,D1 python scripts/scan_hourly.py"""

import os
import sys
from datetime import datetime, timezone

import _bootstrap  # noqa: F401
from lib import state
from lib.scanner import run_scan

STATEFUL_TFS = ("H4", "D1")


def due_timeframes(hour: int) -> list[str]:
    """Aturan lama berbasis jam (dipakai hanya kalau state tidak bisa dibaca)."""
    tfs = ["H1"]
    if hour % 4 == 0:
        tfs.append("H4")
    if hour == 0:
        tfs.append("D1")
    return tfs


def tf_bucket(tf: str, now: datetime) -> str:
    """ID candle terakhir yang sudah close. Candle 4h Twelve Data (UTC) tutup
    jam 01/05/09/13/17/21; candle harian tutup 00:00 UTC."""
    eh = int(now.timestamp() // 3600)
    if tf == "H4":
        return str((eh - 1) // 4)
    if tf == "D1":
        return now.strftime("%Y-%m-%d")
    return str(eh)


def due_stateful(now: datetime, get_value=state.get_value) -> list[str]:
    tfs = ["H1"]
    for tf in STATEFUL_TFS:
        if get_value(f"scan:last:{tf}") != tf_bucket(tf, now):
            tfs.append(tf)
    return tfs


def main() -> int:
    now = datetime.now(timezone.utc)
    forced = os.environ.get("SCAN_FORCE", "").strip()
    dry = os.environ.get("DRY_RUN", "false").strip().lower() == "true"
    if forced:
        tfs = [t.strip().upper() for t in forced.split(",") if t.strip()]
    else:
        try:
            tfs = due_stateful(now)
        except Exception as e:  # noqa: BLE001 — state mati → aturan lama
            print(f"[warn] state scan:last tidak terbaca ({e}) → aturan jam")
            tfs = due_timeframes(now.hour)
    print(f"[hourly] {now.isoformat()} → {tfs}")
    rc = 0
    for tf in tfs:
        r = run_scan(tf)
        rc = max(rc, r)
        if r == 0 and not dry and tf in STATEFUL_TFS:
            try:
                state.set_value(f"scan:last:{tf}", tf_bucket(tf, now))
            except Exception as e:  # noqa: BLE001
                print(f"[warn] gagal menyimpan scan:last:{tf} ({e})")
    return rc


if __name__ == "__main__":
    sys.exit(main())
