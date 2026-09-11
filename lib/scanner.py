"""Shared scan runner. scripts/scan_h4.py & scan_d1.py memanggil run_scan()."""

from __future__ import annotations

import json
import os
import sys
import traceback
from datetime import datetime, timezone

from config import settings
from config.pairs import MAJOR_PAIRS
from lib.claude_grader import grade_setup
from lib.grading import enrich_levels, htf_alignment, htf_trend, pre_grade, rule_grade
from lib.harmonics import build_candidate, extract_xabcd, match_pattern
from lib.pivots import swing_pivots
from lib.prz import construct_prz
from lib.state import backend_name, is_already_signaled, mark_signaled
from lib.telegram import send_signal
from lib.twelvedata import TwelveDataClient

INTERVAL_OF = {"H4": "4h", "D1": "1day"}


def is_forex_closed(now: datetime | None = None) -> bool:
    now = now or datetime.now(timezone.utc)
    weekday, hour = now.weekday(), now.hour
    if weekday == 5:
        return True
    if weekday == 6 and hour < 22:
        return True
    if weekday == 4 and hour >= 22:
        return True
    return False


def analyze_candles(pair: str, timeframe: str, candles: list[dict]) -> list[dict]:
    """Pure function: candles → kandidat lengkap (PRZ/SL/TP/RR/pre_grade).
    Tidak menyentuh network. Dipakai scanner & scan_pair & tests."""
    pivots = swing_pivots(candles, settings.PIVOT_LEFT, settings.PIVOT_RIGHT, settings.MIN_LEG_ATR)
    structures = extract_xabcd(pivots, candles)
    out = []
    for match in match_pattern(structures):
        cand = build_candidate(pair, timeframe, match, candles)
        construct_prz(cand, pivots)
        enrich_levels(cand)
        cand["pre_grade"] = pre_grade(cand)
        out.append(cand)
    return out


def _utf8_console() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def run_scan(timeframe: str, pairs: list[str] | None = None, dry_run: bool | None = None) -> int:
    _utf8_console()
    if is_forex_closed():
        print(f"[skip] Forex market closed ({datetime.now(timezone.utc).isoformat()})")
        return 0

    pairs = pairs or MAJOR_PAIRS
    if dry_run is None:
        dry_run = os.environ.get("DRY_RUN", "false").lower() == "true"
    interval = INTERVAL_OF[timeframe]
    htf_interval = settings.HTF_OF[timeframe]
    print(f"[start] {timeframe} scan · {len(pairs)} pair · DRY_RUN={dry_run} · "
          f"state={backend_name()} · model={settings.CLAUDE_MODEL}")

    tdc = TwelveDataClient(api_key=settings.env("TWELVEDATA_API_KEY"))

    stats = {k: 0 for k in ("pairs_scanned", "structures_matched", "skipped_pregrade",
                            "skipped_duplicate", "grade_c", "signals_sent")}
    errors: list[dict] = []

    for pair in pairs:
        try:
            candles = tdc.get_candles(pair, interval, outputsize=200)
            stats["pairs_scanned"] += 1
            if len(candles) < 50:
                print(f"[warn] {pair}: hanya {len(candles)} candle, skip")
                continue

            cands = analyze_candles(pair, timeframe, candles)
            stats["structures_matched"] += len(cands)
            htf_candles = None

            for cand in cands:
                tag = f"{pair} {cand['pattern']} {cand['direction']} ({'proj' if cand['d_projected'] else 'done'})"
                if cand["pre_grade"] == "FAIL":
                    stats["skipped_pregrade"] += 1
                    print(f"[pregrade-fail] {tag}: {cand['pre_grade_reason']}")
                    continue
                if is_already_signaled(cand):
                    stats["skipped_duplicate"] += 1
                    print(f"[dup] {tag}")
                    continue

                # HTF lazy fetch — hanya untuk kandidat yang lolos pre-grade
                if htf_candles is None:
                    try:
                        htf_candles = tdc.get_candles(pair, htf_interval, outputsize=settings.HTF_OUTPUTSIZE)
                    except Exception as e:  # noqa: BLE001
                        print(f"[warn] {pair}: HTF fetch gagal ({e}), alignment=neutral")
                        htf_candles = []
                trend = htf_trend(htf_candles) if htf_candles else "neutral"
                cand["htf_timeframe"] = htf_interval
                cand["htf_trend"] = trend
                cand["htf_alignment"] = htf_alignment(cand, trend)
                rule_grade(cand)

                grade = grade_setup(cand)
                print(f"[grade] {tag}: {grade['grade']} (rule {cand['rule_grade']['grade']}, src {grade['source']})")
                if grade["grade"] == "C":
                    stats["grade_c"] += 1
                    continue

                if dry_run:
                    print(f"[dry_run] Would send: {tag} Grade {grade['grade']}")
                else:
                    send_signal(cand, grade)
                    mark_signaled(cand)
                    print(f"[sent] {tag} Grade {grade['grade']}")
                stats["signals_sent"] += 1

        except Exception as e:  # noqa: BLE001
            errors.append({"pair": pair, "error": str(e), "traceback": traceback.format_exc()})
            print(f"[error] {pair}: {e}", file=sys.stderr)

    summary = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "timeframe": timeframe,
        "dry_run": dry_run,
        **stats,
        "twelvedata_requests": tdc.request_count,
        "errors_count": len(errors),
        "errors": [{"pair": e["pair"], "error": e["error"]} for e in errors[:5]],
    }
    print("[summary]", json.dumps(summary, indent=2))

    if errors and len(errors) == len(pairs):
        print("[FATAL] Semua pair error — kemungkinan credentials / API down", file=sys.stderr)
        return 1
    return 0
