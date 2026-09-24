"""Strategi kandidat: Trend Pullback (24 Sep 2026) — mekanis, untuk backtest.

Aturan (bull; bear cermin):
  trend    : EMA50 > EMA200 dan close terakhir > EMA50 (semua dari bar yang sudah close)
  pullback : ada bar dalam PB_LOOKBACK bar terakhir yang low-nya <= EMA20 (menyentuh EMA20)
  trigger  : close bar terakhir > high bar sebelumnya dan close > EMA20 (lanjutan trend)
  entry    : market di open bar berikutnya
  SL       : min(low) dari bar pullback (PB_LOOKBACK + 1 bar) - SL_ATR x ATR14
  TP       : entry + TP_R x jarak SL (satu posisi penuh); opsi split 50/50 di 1R & TP_R + BE
  filter   : 0.5 ATR <= jarak SL <= 3 ATR, satu posisi per simbol, cooldown COOLDOWN bar,
             opsi HTF: trend HTF (EMA50 vs EMA200) harus searah.
Semua fungsi murni; engine backtest sendiri (lib/backtest.py dipakai untuk ringkasan).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from config.pairs import asset_class, pip_size
from config import settings
from lib.exec_rules import INTERVAL_SEC, parse_dt


@dataclass
class TPParams:
    tp_r: float = 2.0
    split: bool = False        # 50% di 1R + BE, 50% di tp_r
    pb_lookback: int = 5
    sl_atr: float = 0.2
    min_risk_atr: float = 0.5
    max_risk_atr: float = 3.0
    cooldown: int = 3
    htf_filter: bool = False   # trend HTF harus searah
    ema_fast: int = 20
    ema_mid: int = 50
    ema_slow: int = 200


def ema_series(values: list[float], period: int) -> list[float]:
    k = 2 / (period + 1)
    out = [values[0]]
    for v in values[1:]:
        out.append(v * k + out[-1] * (1 - k))
    return out


def atr_series(bars: list[dict], period: int = 14) -> list[float]:
    out = [0.0]
    trs = []
    for i in range(1, len(bars)):
        h, l, pc = bars[i]["high"], bars[i]["low"], bars[i - 1]["close"]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
        w = trs[-period:]
        out.append(sum(w) / len(w))
    return out


def signal_at(bars: list[dict], i: int, e20: list[float], e50: list[float], e200: list[float],
              atr: list[float], p: TPParams) -> dict | None:
    """Sinyal untuk entry di open bar i, memakai bar 0..i-1 (sudah close)."""
    j = i - 1
    if j < p.ema_slow + p.pb_lookback + 2:
        return None
    c, h, l = bars[j]["close"], bars[j]["high"], bars[j]["low"]
    a = atr[j]
    if a <= 0:
        return None
    up = e50[j] > e200[j] and c > e50[j]
    dn = e50[j] < e200[j] and c < e50[j]
    if not (up or dn):
        return None
    lo_win = range(j - p.pb_lookback, j + 1)
    if up:
        touched = any(bars[k]["low"] <= e20[k] for k in lo_win)
        trig = c > bars[j - 1]["high"] and c > e20[j]
        if not (touched and trig):
            return None
        sl = min(bars[k]["low"] for k in lo_win) - p.sl_atr * a
        entry = bars[i]["open"]
        risk = entry - sl
    else:
        touched = any(bars[k]["high"] >= e20[k] for k in lo_win)
        trig = c < bars[j - 1]["low"] and c < e20[j]
        if not (touched and trig):
            return None
        sl = max(bars[k]["high"] for k in lo_win) + p.sl_atr * a
        entry = bars[i]["open"]
        risk = sl - entry
    if risk < p.min_risk_atr * a or risk > p.max_risk_atr * a:
        return None
    return {"direction": "bull" if up else "bear", "entry": entry, "sl": sl, "risk": risk, "atr": a}


def run_pair(pair: str, tf: str, bars: list[dict], htf_bars: list[dict] | None, p: TPParams,
             last_n: int | None = None) -> list[dict]:
    closes = [b["close"] for b in bars]
    e20, e50, e200 = ema_series(closes, p.ema_fast), ema_series(closes, p.ema_mid), ema_series(closes, p.ema_slow)
    atr = atr_series(bars)
    ep = [parse_dt(b["datetime"]).timestamp() for b in bars]
    # HTF trend as-of (bar HTF yang sudah close)
    htf_dir: list[str | None] = []
    if p.htf_filter and htf_bars:
        hc = [b["close"] for b in htf_bars]
        h50, h200 = ema_series(hc, p.ema_mid), ema_series(hc, p.ema_slow)
        hep = [parse_dt(b["datetime"]).timestamp() for b in htf_bars]
        hsec = INTERVAL_SEC[settings.HTF_OF[tf]]
        hj = 0
        for t in ep:
            while hj < len(htf_bars) and hep[hj] + hsec <= t:
                hj += 1
            k = hj - 1
            htf_dir.append(None if k < p.ema_slow else ("bull" if h50[k] > h200[k] else "bear"))
    cls = asset_class(pair)
    spread = pip_size(pair) if cls == "forex" else settings.BT_SPREAD.get(cls, 0.0001)
    start = max(p.ema_slow + 10, len(bars) - last_n) if last_n else p.ema_slow + 10
    pos: dict | None = None
    last_exit_i = -10 ** 9
    trades: list[dict] = []
    for i in range(start, len(bars)):
        b = bars[i]
        o_, h_, l_ = b["open"], b["high"], b["low"]
        # kelola posisi (SL dulu kalau dua-duanya kena; bar fill = market di open → TP boleh)
        if pos is not None:
            buy = pos["direction"] == "bull"
            for name, leg in pos["legs"].items():
                if not leg["open"]:
                    continue
                sl, tp = leg["sl"], leg["tp"]
                hit_sl = l_ <= sl if buy else h_ >= sl
                hit_tp = h_ >= tp if buy else l_ <= tp
                if hit_sl:
                    px = min(o_, sl) if buy else max(o_, sl)
                    pos["r"] += leg["w"] * ((px - pos["entry"]) if buy else (pos["entry"] - px)) / pos["risk"]
                    leg["open"] = False
                    leg["exit"] = "be" if abs(sl - pos["entry"]) < 1e-12 else "sl"
                elif hit_tp:
                    px = max(o_, tp) if buy else min(o_, tp)
                    pos["r"] += leg["w"] * abs(px - pos["entry"]) / pos["risk"]
                    leg["open"] = False
                    leg["exit"] = name
                    if name == "tp1" and pos["legs"].get("tp2", {}).get("open"):
                        pos["legs"]["tp2"]["sl"] = pos["entry"]
            if not any(lg["open"] for lg in pos["legs"].values()):
                cost = (spread if cls == "forex" else spread * pos["entry"]) / pos["risk"]
                fill_dt = datetime.fromtimestamp(pos["fill_ts"], timezone.utc)
                trades.append({
                    "pair": pair, "tf": tf, "kind": "trend_pullback", "pattern": "TP", "direction": pos["direction"],
                    "grade": "-", "stage": "-", "htf": pos.get("htf", "n/a"), "exec_mode": "market", "order": "market",
                    "entry": pos["entry"], "sl": pos["sl"],
                    "tp1": (pos["legs"]["tp1"] if "tp1" in pos["legs"] else pos["legs"]["tpR"])["tp"],
                    "tp2": (pos["legs"]["tp2"] if "tp2" in pos["legs"] else pos["legs"]["tpR"])["tp"],
                    "rr1": 1.0 if p.split else p.tp_r, "rr2": p.tp_r,
                    "placed": fill_dt.isoformat(timespec="minutes"), "fill": fill_dt.isoformat(timespec="minutes"),
                    "fill_hour": fill_dt.hour, "exit": datetime.fromtimestamp(ep[i], timezone.utc).isoformat(timespec="minutes"),
                    "exit_ts": ep[i], "bars_held": i - pos["fill_i"], "legs": {k: v.get("exit") for k, v in pos["legs"].items()},
                    "r": round(pos["r"], 4), "cost_r": round(cost, 4), "r_net": round(pos["r"] - cost, 4),
                    "result": "win" if pos["r"] > 1e-9 else ("loss" if pos["r"] < -1e-9 else "flat"),
                    "risk_atr": round(pos["risk"] / pos["atr"], 2),
                })
                last_exit_i = i
                pos = None
            continue
        # sinyal baru (tanpa posisi, lewat cooldown)
        if i - last_exit_i < p.cooldown:
            continue
        sig = signal_at(bars, i, e20, e50, e200, atr, p)
        if sig is None:
            continue
        if p.htf_filter:
            hd = htf_dir[i] if htf_dir else None
            if hd is None or hd != sig["direction"]:
                continue
        sign = 1 if sig["direction"] == "bull" else -1
        e, r = sig["entry"], sig["risk"]
        if p.split:
            legs = {"tp1": {"sl": sig["sl"], "tp": e + sign * 1.0 * r, "open": True, "w": 0.5},
                    "tp2": {"sl": sig["sl"], "tp": e + sign * p.tp_r * r, "open": True, "w": 0.5}}
        else:
            legs = {"tpR": {"sl": sig["sl"], "tp": e + sign * p.tp_r * r, "open": True, "w": 1.0}}
        pos = {**sig, "legs": legs, "r": 0.0, "fill_i": i, "fill_ts": ep[i],
               "htf": "aligned" if p.htf_filter else "n/a"}
        # bar fill (market di open): SL/TP boleh dievaluasi di bar ini juga
        buy = sig["direction"] == "bull"
        for name, leg in pos["legs"].items():
            sl, tp = leg["sl"], leg["tp"]
            hit_sl = l_ <= sl if buy else h_ >= sl
            hit_tp = h_ >= tp if buy else l_ <= tp
            if hit_sl:
                pos["r"] += leg["w"] * ((sl - e) if buy else (e - sl)) / r
                leg["open"] = False
                leg["exit"] = "sl"
            elif hit_tp:
                pos["r"] += leg["w"] * abs(tp - e) / r
                leg["open"] = False
                leg["exit"] = name
                if name == "tp1" and pos["legs"].get("tp2", {}).get("open"):
                    pos["legs"]["tp2"]["sl"] = e
        if not any(lg["open"] for lg in pos["legs"].values()):
            cost = (spread if cls == "forex" else spread * e) / r
            fill_dt = datetime.fromtimestamp(ep[i], timezone.utc)
            trades.append({
                "pair": pair, "tf": tf, "kind": "trend_pullback", "pattern": "TP", "direction": sig["direction"],
                "grade": "-", "stage": "-", "htf": pos["htf"], "exec_mode": "market", "order": "market",
                "entry": e, "sl": sig["sl"], "tp1": e + sign * r, "tp2": e + sign * p.tp_r * r, "rr1": 1.0, "rr2": p.tp_r,
                "placed": fill_dt.isoformat(timespec="minutes"), "fill": fill_dt.isoformat(timespec="minutes"),
                "fill_hour": fill_dt.hour, "exit": fill_dt.isoformat(timespec="minutes"), "exit_ts": ep[i], "bars_held": 0,
                "legs": {k: v.get("exit") for k, v in pos["legs"].items()},
                "r": round(pos["r"], 4), "cost_r": round(cost, 4), "r_net": round(pos["r"] - cost, 4),
                "result": "win" if pos["r"] > 1e-9 else ("loss" if pos["r"] < -1e-9 else "flat"),
                "risk_atr": round(r / sig["atr"], 2),
            })
            last_exit_i = i
            pos = None
    return trades
