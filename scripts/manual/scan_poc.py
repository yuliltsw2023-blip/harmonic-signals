#!/usr/bin/env python3
"""Debug POC pullback untuk satu simbol (forex/crypto via Twelve Data, saham
via Yahoo — otomatis dari config.pairs.data_source).

python scripts/manual/scan_poc.py EUR/USD H4
python scripts/manual/scan_poc.py BBCA.JK D1 --send
python scripts/manual/scan_poc.py AAPL D1 --csv data/aapl.csv
"""

import argparse
import csv
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _bootstrap_manual  # noqa: F401,E402

from config import settings  # noqa: E402
from config.pairs import data_source, price_decimals  # noqa: E402
from lib.grading import htf_trend  # noqa: E402
from lib.poc import analyze_poc, poc_alignment, rule_grade_poc  # noqa: E402
from lib.scanner import INTERVAL_OF  # noqa: E402
from lib.telegram import format_poc_signal, send_poc_signal  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("pair")
ap.add_argument("timeframe", nargs="?", default="H4", choices=["H1", "H4", "D1"])
ap.add_argument("--csv", help="datetime,open,high,low,close[,volume]")
ap.add_argument("--send", action="store_true", help="kirim ke Telegram")
ap.add_argument("--json", action="store_true", help="dump kandidat mentah")
args = ap.parse_args()

if args.csv:
    with open(args.csv, newline="") as fh:
        candles = []
        for r in csv.DictReader(fh):
            c = {"datetime": r["datetime"], "open": float(r["open"]), "high": float(r["high"]),
                 "low": float(r["low"]), "close": float(r["close"])}
            if r.get("volume"):
                c["volume"] = float(r["volume"])
            candles.append(c)
    client = None
else:
    if data_source(args.pair) == "yahoo":
        from lib.yahoo import YahooClient
        client = YahooClient()
    else:
        from lib.twelvedata import TwelveDataClient
        client = TwelveDataClient(api_key=settings.env("TWELVEDATA_API_KEY"))
    candles = client.get_candles(args.pair, INTERVAL_OF[args.timeframe], outputsize=200)

d = price_decimals(args.pair)
print(f"{args.pair} {args.timeframe}: {len(candles)} candle, last {candles[-1]['datetime']} "
      f"close {candles[-1]['close']:.{d}f}, volume={'ya' if 'volume' in candles[-1] else 'tidak (TPO)'}")

from lib.pivots import swing_pivots  # noqa: E402
n = settings.POC_PIVOT[args.timeframe]
pivots = swing_pivots(candles, n, n, settings.MIN_LEG_ATR)
print(f"pivot {n}/{n}: {len(pivots)}, 6 terakhir: " +
      ", ".join(f"{p['type']} {p['price']:.{d}f} @{p['datetime'][:10]}" for p in pivots[-6:]))

cand = analyze_poc(args.pair, args.timeframe, candles)
if cand is None:
    print("Tidak ada kandidat: butuh ≥2 swing high + ≥2 swing low terkonfirmasi dan leg ≥3 candle.")
    sys.exit(0)

print(f"\nbias={cand['bias']} arah leg={cand['direction']} stage={cand['stage']} "
      f"leg={cand['leg']['bars']} bar {cand['leg']['start_price']:.{d}f}→{cand['leg']['end_price']:.{d}f}")
print(f"POC {cand['poc']:.{d}f} | VAH {cand['vah']:.{d}f} | VAL {cand['val']:.{d}f} | "
      f"kedalaman {cand['depth']:.2f} ({cand['depth_label']}) | profile {cand['profile']['source']}")
print(f"pre-grade: {cand['pre_grade']} ({cand['pre_grade_reason']})")

if client is not None:
    try:
        htf = client.get_candles(args.pair, settings.HTF_OF[args.timeframe], outputsize=settings.HTF_OUTPUTSIZE)
        trend = htf_trend(htf)
    except Exception as e:  # noqa: BLE001
        print(f"[warn] HTF gagal: {e}")
        trend = "neutral"
else:
    trend = "neutral"
cand["htf_timeframe"] = settings.HTF_OF[args.timeframe]
cand["htf_trend"] = trend
cand["htf_alignment"] = poc_alignment(cand, trend)
g = rule_grade_poc(cand)
print(f"grade: {g['grade']} {g['factors']}")

if args.json:
    print(json.dumps(cand, indent=2, default=str))
print("\n" + format_poc_signal(cand).replace("<b>", "").replace("</b>", "").replace("<i>", "").replace("</i>", ""))
if args.send:
    send_poc_signal(cand)
    print("[sent]")
