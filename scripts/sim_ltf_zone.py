#!/usr/bin/env python3
"""Simulasi strategi "zona HTF + trigger LTF" (docs/XAU-STRATEGI-2026-09-28.md).

Zona  : level D1 dari pivot terkonfirmasi (fractal 3) + fib 0,618/0,786 leg D1 terakhir,
        lebar ±ZONE_ATR × ATR14 D1. Hanya info D1 yang sudah tutup (tanpa look-ahead).
Trigger: harga menyentuh zona (datang dari arah berlawanan), lalu dalam ARM_BARS candle
        LTF muncul close menembus high/low 3 candle sebelumnya (CHoCH mini).
        Batal kalau close menembus zona lebih dari 0,5 ATR D1.
Entry : close candle trigger (07–20 UTC). SL = ekstrem sejak sentuh ∓ 2 poin.
        Skip kalau jarak SL > cap (lot minimal) atau < 2 poin.
Exit  : varian — TP tetap nR, atau SL→BE di +1R lalu trailing fractal-3 di M15/H1
        (sama dengan EA v1.2: SL hanya bergerak searah profit, dari candle yang sudah tutup).
        Candle yang kena SL & TP sekaligus = SL (konservatif). Maks tahan 3 hari.

python scripts/sim_ltf_zone.py [--cap 10] [--ltf 15min]
"""

import argparse
import json
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from lib.pivots import atr  # noqa: E402

H = os.path.join("data", "history")
ap = argparse.ArgumentParser()
ap.add_argument("--ltf", default="15min", choices=["15min", "1h"])
ap.add_argument("--cap", type=float, default=10.0, help="jarak SL maksimal (poin)")
ap.add_argument("--spread", type=float, default=0.35, help="biaya pulang-pergi (poin)")
ap.add_argument("--zone-atr", type=float, default=0.15)
ap.add_argument("--arm-bars", type=int, default=16)
ap.add_argument("--be-r", type=float, default=1.0, help="SL→BE & trailing aktif setelah +N R")
ap.add_argument("--trades", action="store_true", help="cetak daftar trade varian trail H1")
a = ap.parse_args()

ltf = json.load(open(os.path.join(H, f"XAUUSD_{a.ltf}.json" if a.ltf == "15min" else "XAUUSD_1h_fresh.json")))
h1 = json.load(open(os.path.join(H, "XAUUSD_1h_fresh.json")))
d1 = json.load(open(os.path.join(H, "XAUUSD_1day_fresh.json")))
ts = lambda s: datetime.fromisoformat(s).timestamp()  # noqa: E731
for arr in (ltf, h1, d1):
    for b in arr:
        b["t"] = ts(b["datetime"])
LTF_SEC = 900 if a.ltf == "15min" else 3600


def ema(vals, n):
    k, e, out = 2 / (n + 1), vals[0], []
    for v in vals:
        e = v * k + e * (1 - k)
        out.append(e)
    return out


d1_ema = ema([b["close"] for b in d1], 50)


def d1_context(t):
    """Zona & tren dari candle D1 yang sudah TUTUP sebelum waktu t."""
    idx = max(i for i, b in enumerate(d1) if b["t"] + 86400 <= t)
    bars = d1[: idx + 1]
    a14 = atr(bars[-30:])
    piv = []
    for k in range(max(3, len(bars) - 120), len(bars) - 3):
        lo, hi = bars[k]["low"], bars[k]["high"]
        if all(lo < bars[j]["low"] for j in range(k - 3, k)) and all(lo <= bars[j]["low"] for j in range(k + 1, k + 4)):
            piv.append(("L", k, lo))
        if all(hi > bars[j]["high"] for j in range(k - 3, k)) and all(hi >= bars[j]["high"] for j in range(k + 1, k + 4)):
            piv.append(("H", k, hi))
    levels = [p[2] for p in piv]
    lows = [p for p in piv if p[0] == "L"]
    highs = [p for p in piv if p[0] == "H"]
    if lows and highs:
        lo, hi = lows[-1], highs[-1]
        rng = hi[2] - lo[2]
        if hi[1] > lo[1]:   # leg naik terakhir → retracement ke bawah
            levels += [hi[2] - 0.618 * rng, hi[2] - 0.786 * rng]
        else:               # leg turun terakhir → retracement ke atas
            levels += [lo[2] + 0.618 * rng, lo[2] + 0.786 * rng]
    trend = "up" if bars[-1]["close"] > d1_ema[idx] else "down"
    return levels, a14, trend


def fractal_sl(bars, last, buy, n=3):
    for k in range(last - n, max(n - 1, last - 200), -1):
        if buy:
            v = bars[k]["low"]
            if all(v < bars[j]["low"] for j in range(k - n, k)) and all(v <= bars[j]["low"] for j in range(k + 1, k + n + 1)):
                return v
        else:
            v = bars[k]["high"]
            if all(v > bars[j]["high"] for j in range(k - n, k)) and all(v >= bars[j]["high"] for j in range(k + 1, k + n + 1)):
                return v
    return None


# ------------------------------------------------------------------ cari entry
signals, skipped = [], {"sl_terlalu_jauh": 0, "sl_terlalu_dekat": 0}
armed = []          # dict(side, lvl, start, ext, zone_lo, zone_hi)
used = {}           # (side, round(level)) -> t terakhir dipakai
day_cache = {}
start_t = d1[60]["t"]
for i in range(4, len(ltf)):
    b, p = ltf[i], ltf[i - 1]
    if b["t"] < start_t:
        continue
    day = b["datetime"][:10]
    if day not in day_cache:
        day_cache[day] = d1_context(b["t"])
    levels, a14, trend = day_cache[day]
    hw = a.zone_atr * a14
    # sentuhan zona baru
    for lvl in levels:
        zlo, zhi = lvl - hw, lvl + hw
        if p["low"] > zhi and b["low"] <= zhi:
            side = "buy"
        elif p["high"] < zlo and b["high"] >= zlo:
            side = "sell"
        else:
            continue
        key = (side, round(lvl))
        if b["t"] - used.get(key, 0) < 86400:
            continue
        used[key] = b["t"]
        armed.append({"side": side, "lvl": lvl, "start": i, "ext": b["low"] if side == "buy" else b["high"],
                      "zlo": zlo, "zhi": zhi, "a14": a14, "trend": trend})
    keep = []
    for s in armed:
        buy = s["side"] == "buy"
        s["ext"] = min(s["ext"], b["low"]) if buy else max(s["ext"], b["high"])
        broken = (b["close"] < s["zlo"] - 0.5 * s["a14"]) if buy else (b["close"] > s["zhi"] + 0.5 * s["a14"])
        if broken or i - s["start"] > a.arm_bars:
            continue
        prev3 = ltf[i - 3:i]
        trig = (b["close"] > max(x["high"] for x in prev3)) if buy else (b["close"] < min(x["low"] for x in prev3))
        hour = int(b["datetime"][11:13])
        if trig and i > s["start"] and 7 <= hour < 20:
            sl = s["ext"] - 2 if buy else s["ext"] + 2
            risk = abs(b["close"] - sl)
            if risk > a.cap:
                skipped["sl_terlalu_jauh"] += 1
            elif risk < 2:
                skipped["sl_terlalu_dekat"] += 1
            else:
                signals.append({"i": i, "t": b["t"], "dt": b["datetime"], "buy": buy, "entry": b["close"],
                                "sl": sl, "risk": risk, "lvl": s["lvl"],
                                "with_trend": (s["trend"] == "up") == buy})
            continue            # satu trigger per sentuhan
        keep.append(s)
    armed = keep

# ------------------------------------------------------------------ kelola posisi
h1_t = [b["t"] for b in h1]


def simulate(sig, mode):
    """mode: ('tp', n) | ('tpbe', n) = TP nR + SL→BE di +be_r R | ('trail', 'ltf'|'h1')"""
    buy, e, risk = sig["buy"], sig["entry"], sig["risk"]
    sign = 1 if buy else -1
    sl, best, trail_on = sig["sl"], e, False
    tp = e + sign * mode[1] * risk if mode[0] in ("tp", "tpbe") else None
    last_i = min(len(ltf) - 1, sig["i"] + int(3 * 86400 / LTF_SEC))
    for j in range(sig["i"] + 1, last_i + 1):
        c = ltf[j]
        hit_sl = c["low"] <= sl if buy else c["high"] >= sl
        if hit_sl:
            return sign * (sl - e) / risk, j, "SL" if not trail_on else ("BE" if abs(sl - e) < 1e-6 else "TRAIL")
        if tp is not None and (c["high"] >= tp if buy else c["low"] <= tp):
            return mode[1], j, "TP"
        best = max(best, c["high"]) if buy else min(best, c["low"])
        if mode[0] == "tpbe" and not trail_on and sign * (best - e) >= a.be_r * risk:
            trail_on = True
            sl = e
        if mode[0] == "trail":
            if not trail_on and sign * (best - e) >= a.be_r * risk:
                trail_on = True
                sl = max(sl, e) if buy else min(sl, e)
            if trail_on:
                if mode[1] == "ltf":
                    bars, last = ltf, j
                else:
                    last = max(k for k in range(len(h1_t)) if h1_t[k] + 3600 <= c["t"] + LTF_SEC) if h1_t[0] + 3600 <= c["t"] + LTF_SEC else None
                    bars = h1
                if last is not None:
                    f = fractal_sl(bars, last, buy)
                    if f is not None:
                        if buy and sl < f < c["close"]:
                            sl = f
                        elif not buy and c["close"] < f < sl:
                            sl = f
    c = ltf[last_i]
    return sign * (c["close"] - e) / risk, last_i, "TIME"


def run(mode, subset):
    rs, busy_until, out = [], -1, []
    for s in subset:
        if s["i"] <= busy_until:
            continue                            # maks 1 posisi
        r, j, why = simulate(s, mode)
        r_net = r - a.spread / s["risk"]
        busy_until = j
        rs.append(r_net)
        out.append({**s, "r": r_net, "exit": why, "exit_dt": ltf[j]["datetime"], "usd": r_net * s["risk"]})
    return rs, out


def stats(rs):
    if not rs:
        return "n=0"
    w = [r for r in rs if r > 0]
    l = [r for r in rs if r <= 0]
    eq, peak, dd = 0, 0, 0
    for r in rs:
        eq += r
        peak = max(peak, eq)
        dd = max(dd, peak - eq)
    pf = sum(w) / abs(sum(l)) if l and sum(l) else float("inf")
    return (f"n={len(rs):3d} win {100 * len(w) / len(rs):4.0f}%  avgR {sum(rs) / len(rs):+.2f}  ΣR {sum(rs):+6.1f}  "
            f"PF {pf:4.2f}  maxDD {dd:4.1f}R  rata2 menang {sum(w) / len(w) if w else 0:+.2f}R  terbesar {max(rs):+.1f}R")


MODES = [("TP 2R", ("tp", 2)), ("TP 3R", ("tp", 3)), ("TP 2R + BE", ("tpbe", 2)), ("TP 3R + BE", ("tpbe", 3)), ("BE+trail M15" if a.ltf == "15min" else "BE+trail LTF", ("trail", "ltf")),
         ("BE+trail H1", ("trail", "h1"))]
print(f"XAU {a.ltf} · {ltf[0]['datetime'][:10]} → {ltf[-1]['datetime'][:10]} · cap SL {a.cap} poin · biaya {a.spread} poin · BE/trail mulai +{a.be_r}R")
print(f"sinyal: {len(signals)} (long {sum(s['buy'] for s in signals)}, short {sum(not s['buy'] for s in signals)}) · dilewati {skipped}")
if signals:
    print(f"risiko rata-rata {sum(s['risk'] for s in signals) / len(signals):.1f} poin (= ${sum(s['risk'] for s in signals) / len(signals):.2f} per 0,01 lot)")
for label, subset in [("SEMUA", signals), ("searah tren D1", [s for s in signals if s["with_trend"]]),
                      ("lawan tren D1", [s for s in signals if not s["with_trend"]])]:
    print(f"\n== {label}")
    for name, mode in MODES:
        print(f"  {name:13s} {stats(run(mode, subset)[0])}")

if a.trades:
    _, out = run(("trail", "h1"), signals)
    print("\nTrade (BE+trail H1):")
    for t in out:
        print(f"  {t['dt']} {'BUY ' if t['buy'] else 'SELL'} {t['entry']:.2f} SL {t['sl']:.2f} ({t['risk']:.1f}p) "
              f"{'tren' if t['with_trend'] else 'lawan'} → {t['exit']:5s} {t['exit_dt']} {t['r']:+.2f}R (${t['usd']:+.2f})")
