#!/usr/bin/env python3
"""Backtest strategi kandidat Trend Pullback (lib/trend_pullback.py) di data/history.

  python scripts/backtest_trend.py                 # semua varian, D1 + H4, 31 simbol
  python scripts/backtest_trend.py --variant d1_2R --pairs EUR/USD,GBP/USD
"""

import argparse
import json
import os
import sys
from multiprocessing import Pool

import _bootstrap  # noqa: F401
from config import settings
from config.pairs import symbols_for
from lib.backtest import TF_INTERVAL, group_summary, load_history, summarize, weekly_from_daily
from lib.trend_pullback import TPParams, run_pair

VARIANTS = {
    "d1_1.5R": ("D1", TPParams(tp_r=1.5)),
    "d1_2R": ("D1", TPParams(tp_r=2.0)),
    "d1_3R": ("D1", TPParams(tp_r=3.0)),
    "d1_2R_split": ("D1", TPParams(tp_r=2.0, split=True)),
    "d1_2R_htfW1": ("D1", TPParams(tp_r=2.0, htf_filter=True)),
    "h4_1.5R": ("H4", TPParams(tp_r=1.5)),
    "h4_2R": ("H4", TPParams(tp_r=2.0)),
    "h4_3R": ("H4", TPParams(tp_r=3.0)),
    "h4_2R_split": ("H4", TPParams(tp_r=2.0, split=True)),
    "h4_2R_htfD1": ("H4", TPParams(tp_r=2.0, htf_filter=True)),
    "h4_3R_htfD1": ("H4", TPParams(tp_r=3.0, htf_filter=True)),
}
DEFAULT_BARS = {"H4": 5000, "D1": 2500}


def _worker(args):
    pair, tf, params, last_n = args
    try:
        bars = load_history(pair, TF_INTERVAL[tf])
        htf = None
        if params.htf_filter:
            htf_iv = settings.HTF_OF[tf]
            htf = weekly_from_daily(load_history(pair, "1day")) if htf_iv == "1week" else load_history(pair, htf_iv)
    except FileNotFoundError as e:
        return {"pair": pair, "tf": tf, "error": str(e), "trades": []}
    return {"pair": pair, "tf": tf, "trades": run_pair(pair, tf, bars, htf, params, last_n=last_n),
            "from": bars[max(0, len(bars) - last_n)]["datetime"] if last_n else bars[0]["datetime"], "to": bars[-1]["datetime"]}


def run_variant(name, pairs, workers, out_dir):
    tf, params = VARIANTS[name]
    jobs = [(pair, tf, params, DEFAULT_BARS[tf]) for pair in (pairs or symbols_for(tf))]
    if workers > 1:
        with Pool(workers) as pool:
            results = pool.map(_worker, jobs)
    else:
        results = [_worker(j) for j in jobs]
    trades = [t for r in results for t in r["trades"]]
    out = {"variant": name, "tf": tf, "params": params.__dict__, "errors": [r["error"] for r in results if r.get("error")],
           "ranges": {r["pair"]: (r.get("from"), r.get("to")) for r in results if not r.get("error")}, "trades": trades}
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, f"trend_{name}.json"), "w") as f:
        json.dump(out, f, indent=1)
    return out


def print_report(res):
    T = res["trades"]
    print(f"\n==== trend {res['variant']} ({res['tf']}) ==== errors {len(res['errors'])}")
    print("TOTAL", summarize(T))
    for label, key in (("direction", lambda t: t["direction"]), ("tahun", lambda t: t["fill"][:4]),
                       ("pair", lambda t: t["pair"]), ("legs", lambda t: "/".join(str(v) for v in t["legs"].values()))):
        print(f"-- by {label}")
        for k, v in group_summary(T, key).items():
            if v["n"] >= 8 or label != "pair":
                print(f"   {k:<12} {v}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--variant", default="all")
    ap.add_argument("--pairs", default="")
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 1))
    ap.add_argument("--out", default=os.path.join("data", "backtest"))
    a = ap.parse_args()
    pairs = [p.strip() for p in a.pairs.split(",") if p.strip()] or None
    names = list(VARIANTS) if a.variant == "all" else [a.variant]
    results = [run_variant(n, pairs, a.workers, a.out) for n in names]
    for r in results:
        print_report(r)
    if len(results) > 1:
        print("\n==== BANDING (TOTAL) ====")
        for r in results:
            print(f"{r['variant']:<16} {summarize(r['trades'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
