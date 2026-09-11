#!/usr/bin/env python3
"""Debug satu pair: tampilkan pivot, struktur, kandidat & alasan pre-grade.

python scripts/manual/scan_pair.py EUR/USD [H4|D1] [--csv path] [--grade] [--send]

--csv   : pakai file CSV (datetime,open,high,low,close) alih-alih Twelve Data
--grade : lanjut grading Claude untuk kandidat yang lolos pre-grade
--send  : kirim ke Telegram (default cuma print)
"""

import argparse
import csv
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _bootstrap_manual  # noqa: F401,E402

from config import settings  # noqa: E402
from config.pairs import price_decimals  # noqa: E402
from lib.claude_grader import grade_setup  # noqa: E402
from lib.grading import htf_alignment, htf_trend, rule_grade  # noqa: E402
from lib.pivots import swing_pivots  # noqa: E402
from lib.scanner import INTERVAL_OF, analyze_candles  # noqa: E402
from lib.telegram import format_signal, send_signal  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("pair")
ap.add_argument("timeframe", nargs="?", default="H4", choices=["H4", "D1"])
ap.add_argument("--csv")
ap.add_argument("--grade", action="store_true")
ap.add_argument("--send", action="store_true")
ap.add_argument("--png", help="simpan chart ke file PNG")
args = ap.parse_args()

if args.csv:
    with open(args.csv, newline="") as fh:
        candles = [{"datetime": r["datetime"], "open": float(r["open"]), "high": float(r["high"]),
                    "low": float(r["low"]), "close": float(r["close"])} for r in csv.DictReader(fh)]
    tdc = None
else:
    from lib.twelvedata import TwelveDataClient
    tdc = TwelveDataClient(api_key=os.environ["TWELVEDATA_API_KEY"])
    candles = tdc.get_candles(args.pair, INTERVAL_OF[args.timeframe], outputsize=200)

d = price_decimals(args.pair)
print(f"{args.pair} {args.timeframe}: {len(candles)} candle, last {candles[-1]['datetime']} close {candles[-1]['close']:.{d}f}")

pivots = swing_pivots(candles, settings.PIVOT_LEFT, settings.PIVOT_RIGHT, settings.MIN_LEG_ATR)
print(f"\npivots ({len(pivots)}), 8 terakhir:")
for p in pivots[-8:]:
    print(f"  {p['type']} {p['price']:.{d}f} @ {p['datetime']} (bar {p['idx']})")

cands = analyze_candles(args.pair, args.timeframe, candles)
print(f"\nkandidat: {len(cands)}")
for c in cands:
    print(f"\n— {c['pattern']} {c['direction']} {'projected' if c['d_projected'] else 'completed'} "
          f"| pre-grade {c['pre_grade']} ({c['pre_grade_reason']})")
    print("  ratios:", {k: round(v, 3) for k, v in c["ratios"].items()})
    print("  deviasi:", {k: f"{v:.1%}" for k, v in c["deviations"].items()})
    print(f"  PRZ {c['prz']['low']:.{d}f}–{c['prz']['high']:.{d}f} conf={c['prz']['confluence']} "
          f"| SL {c['sl']:.{d}f} | RR tp2 {c['rr']['tp2']:.2f} | jarak {c['prz_distance_pct']:.2%}")

    if args.grade and c["pre_grade"] == "PASS":
        trend = "neutral"
        if tdc is not None:
            htf = tdc.get_candles(args.pair, settings.HTF_OF[args.timeframe], outputsize=settings.HTF_OUTPUTSIZE)
            trend = htf_trend(htf)
        c["htf_timeframe"] = settings.HTF_OF[args.timeframe]
        c["htf_trend"] = trend
        c["htf_alignment"] = htf_alignment(c, trend)
        rule_grade(c)
        g = grade_setup(c)
        print("  grade:", json.dumps(g, ensure_ascii=False, indent=2))
        print("\n" + format_signal(c, g))
        if args.png:
            from lib.chart import render_signal_chart
            with open(args.png, "wb") as fh:
                fh.write(render_signal_chart(c, candles, g))
            print("  chart:", args.png)
        if args.send:
            print(send_signal(c, g, candles))
