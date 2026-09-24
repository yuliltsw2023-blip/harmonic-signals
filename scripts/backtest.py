#!/usr/bin/env python3
"""Backtest scanner + eksekutor di histori lokal (data/history, unduh dulu
dengan scripts/manual/fetch_history.py).

  python scripts/backtest.py --variant v0_live --tf H1,H4,D1
  python scripts/backtest.py --variant v2_confirmed --tf H4 --pairs EUR/USD,GBP/USD
  python scripts/backtest.py --variant all            # semua varian, ringkasan banding

Varian = kombinasi setting eksekusi (lihat VARIANTS). Hasil per trade disimpan ke
data/backtest/<variant>.json; ringkasan dicetak per kind/TF/grade/sesi/HTF.
Catatan model: grade = rule grade (Claude hanya bisa menurunkan), tanpa spread,
tanpa batas 3 setup aktif — angka absolut optimis, gunakan untuk BANDING antar
varian dan filter."""

import argparse
import json
import os
import sys
from multiprocessing import Pool

import _bootstrap  # noqa: F401
from config import settings
from config.pairs import symbols_for
from lib.backtest import PairBacktest, TF_INTERVAL, group_summary, load_history, summarize, weekly_from_daily

BASE_FIX = dict(CLOSED_CANDLE_ONLY=True, SETUP_ID_BY_C=True,
                POC_CANCEL_ON_STAGE=("broken", "continued", "left_va", "below_va"),
                PRZ_BAND_XA=0.0, POC_MIN_LEG_ATR=0.0, POC_TIMEFRAMES=("H1", "H4", "D1"),
                MTF_CONFLICT_FILTER=False, MTF_OWN_TREND=False)
VARIANTS = {
    # persis perilaku live sampai 24 Sep 2026
    "v0_live": dict(CLOSED_CANDLE_ONLY=False, HARMONIC_EXEC_MODE="limit", POC_EXEC_MODE="limit",
                    EXEC_MIN_GRADE="B", EXEC_SESSION_UTC=(), SETUP_ID_BY_C=False, POC_CANCEL_ON_STAGE=(),
                    PRZ_BAND_XA=0.0, POC_MIN_LEG_ATR=0.0, POC_TIMEFRAMES=("H1", "H4", "D1"),
                    MTF_CONFLICT_FILTER=False, MTF_OWN_TREND=False),
    # bug fix saja: candle closed-only, satu ID per pattern, cancel POC saat struktur patah
    "v1_fix": dict(BASE_FIX, HARMONIC_EXEC_MODE="limit", POC_EXEC_MODE="limit", EXEC_MIN_GRADE="B", EXEC_SESSION_UTC=()),
    # + entry hanya setelah konfirmasi (D pivot / candle reaksi), market, SL di luar D / ekstrem pullback
    "v2_confirmed": dict(BASE_FIX, HARMONIC_EXEC_MODE="confirmed", POC_EXEC_MODE="confirmed",
                         EXEC_MIN_GRADE="B", EXEC_SESSION_UTC=()),
    # + hanya Grade A yang dieksekusi
    "v3_confirmed_A": dict(BASE_FIX, HARMONIC_EXEC_MODE="confirmed", POC_EXEC_MODE="confirmed",
                           EXEC_MIN_GRADE="A", EXEC_SESSION_UTC=()),
    # + entry H1/H4 forex hanya 06–20 UTC (London–NY)
    "v4_confirmed_A_session": dict(BASE_FIX, HARMONIC_EXEC_MODE="confirmed", POC_EXEC_MODE="confirmed",
                                   EXEC_MIN_GRADE="A", EXEC_SESSION_UTC=(6, 20)),
    # limit lama tapi hanya Grade A
    "v5_limit_A": dict(BASE_FIX, HARMONIC_EXEC_MODE="limit", POC_EXEC_MODE="limit", EXEC_MIN_GRADE="A", EXEC_SESSION_UTC=()),
    # v2 + filter struktur: PRZ dibatasi 6% XA, leg POC minimal 2×ATR
    "v6_confirmed_struct": dict(BASE_FIX, HARMONIC_EXEC_MODE="confirmed", POC_EXEC_MODE="confirmed",
                                EXEC_MIN_GRADE="B", EXEC_SESSION_UTC=(), PRZ_BAND_XA=0.06, POC_MIN_LEG_ATR=2.0),
    # v1 tanpa POC D1 (default produksi sejak 24 Sep 2026)
    "v8_fix_noPocD1": dict(BASE_FIX, HARMONIC_EXEC_MODE="limit", POC_EXEC_MODE="limit", EXEC_MIN_GRADE="B",
                           EXEC_SESSION_UTC=(), POC_TIMEFRAMES=("H1", "H4")),
    # v8 + filter konflik struktur LTF (D1→H4, H4→H1)
    "v9_conflict_ltf": dict(BASE_FIX, HARMONIC_EXEC_MODE="limit", POC_EXEC_MODE="limit", EXEC_MIN_GRADE="B",
                            EXEC_SESSION_UTC=(), POC_TIMEFRAMES=("H1", "H4"), MTF_CONFLICT_FILTER=True),
    # v9 + trend EMA20/50 di TF sinyal sendiri juga harus searah
    "v10_conflict_ltf_own": dict(BASE_FIX, HARMONIC_EXEC_MODE="limit", POC_EXEC_MODE="limit", EXEC_MIN_GRADE="B",
                                 EXEC_SESSION_UTC=(), POC_TIMEFRAMES=("H1", "H4"), MTF_CONFLICT_FILTER=True,
                                 MTF_OWN_TREND=True),
    # v6 + hanya Grade A + sesi London–NY
    "v7_confirmed_struct_A_session": dict(BASE_FIX, HARMONIC_EXEC_MODE="confirmed", POC_EXEC_MODE="confirmed",
                                          EXEC_MIN_GRADE="A", EXEC_SESSION_UTC=(6, 20), PRZ_BAND_XA=0.06, POC_MIN_LEG_ATR=2.0),
}
DEFAULT_BARS = {"H1": 5000, "H4": 2500, "D1": 1500}


def apply_variant(overrides: dict) -> None:
    for k, v in overrides.items():
        setattr(settings, k, v)


def _worker(args):
    pair, tf, overrides, last_n = args
    apply_variant(overrides)
    try:
        bars = load_history(pair, TF_INTERVAL[tf])
        htf_iv = settings.HTF_OF[tf]
        htf = weekly_from_daily(load_history(pair, "1day")) if htf_iv == "1week" else load_history(pair, htf_iv)
    except FileNotFoundError as e:
        return {"pair": pair, "tf": tf, "error": str(e), "trades": [], "stats": {}}
    ltf_iv = settings.LTF_OF.get(tf)
    ltf = None
    if ltf_iv:
        try:
            ltf = load_history(pair, ltf_iv)
        except FileNotFoundError:
            ltf = None
    bt = PairBacktest(pair, tf, bars, htf, last_n=last_n, ltf_bars=ltf)
    return bt.run()


def run_variant(name: str, tfs: list[str], pairs: list[str] | None, bars: dict, workers: int, out_dir: str) -> dict:
    overrides = VARIANTS[name]
    jobs = []
    for tf in tfs:
        for pair in (pairs or symbols_for(tf)):
            jobs.append((pair, tf, overrides, bars.get(tf)))
    print(f"[{name}] {len(jobs)} job (pair×TF), workers={workers}", flush=True)
    if workers > 1:
        with Pool(workers) as pool:
            results = pool.map(_worker, jobs)
    else:
        results = [_worker(j) for j in jobs]
    trades = [t for r in results for t in r["trades"]]
    stats = {}
    for r in results:
        for k, v in r.get("stats", {}).items():
            stats[k] = stats.get(k, 0) + v
    errors = [r for r in results if r.get("error")]
    out = {"variant": name, "settings": {k: (list(v) if isinstance(v, tuple) else v) for k, v in overrides.items()},
           "tfs": tfs, "stats": stats, "errors": [e["error"] for e in errors],
           "ranges": {f"{r['pair']} {r['tf']}": (r.get("from"), r.get("to")) for r in results if not r.get("error")},
           "trades": trades}
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, f"{name}.json"), "w") as f:
        json.dump(out, f, indent=1)
    return out


def print_report(res: dict) -> None:
    trades = res["trades"]
    print(f"\n==== {res['variant']} ==== stats {res['stats']}  errors {len(res['errors'])}")
    print("TOTAL", summarize(trades))
    for label, key in (("kind", lambda t: t["kind"]), ("tf", lambda t: t["tf"]), ("grade", lambda t: t["grade"]),
                       ("kind×tf", lambda t: f"{t['kind']} {t['tf']}"), ("pattern", lambda t: t["pattern"]),
                       ("htf", lambda t: t["htf"]), ("order", lambda t: t["order"]),
                       ("LTF bias vs arah", lambda t: "n/a" if t.get("ltf_bias") is None else ("KONFLIK" if t.get("conflict_ltf") else "searah")),
                       ("own trend vs arah", lambda t: "n/a" if t.get("own_trend") == "neutral" else ("KONFLIK" if t.get("conflict_own") else "searah")),
                       ("fill_hour(UTC)", lambda t: f"{t['fill_hour']:02d}"),
                       ("direction", lambda t: t["direction"])):
        print(f"-- by {label}")
        for k, v in group_summary(trades, key).items():
            print(f"   {k:<14} {v}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--variant", default="v0_live", help="nama varian atau 'all'")
    ap.add_argument("--tf", default="H1,H4,D1")
    ap.add_argument("--pairs", default="")
    ap.add_argument("--bars", default="", help="mis. H1=5000,H4=2500,D1=1500 (bar terakhir yang di-scan)")
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 1))
    ap.add_argument("--out", default=os.path.join("data", "backtest"))
    a = ap.parse_args()
    tfs = [t.strip().upper() for t in a.tf.split(",") if t.strip()]
    pairs = [p.strip() for p in a.pairs.split(",") if p.strip()] or None
    bars = dict(DEFAULT_BARS)
    for kv in filter(None, a.bars.split(",")):
        k, v = kv.split("=")
        bars[k.strip().upper()] = int(v)
    names = list(VARIANTS) if a.variant == "all" else [a.variant]
    results = []
    for name in names:
        res = run_variant(name, tfs, pairs, bars, a.workers, a.out)
        print_report(res)
        results.append(res)
    if len(results) > 1:
        print("\n==== BANDING (TOTAL) ====")
        for r in results:
            print(f"{r['variant']:<24} {summarize(r['trades'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
