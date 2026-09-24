"""Trend Pullback (lib/trend_pullback.py): sinyal, SL/TP, engine dasar."""

from datetime import datetime, timedelta, timezone

from lib.trend_pullback import TPParams, atr_series, ema_series, run_pair, signal_at


def _uptrend_with_pullback(n_trend=260, dip=6):
    """Uptrend halus (EMA50 > EMA200), lalu pullback singkat ke bawah EMA20, lalu candle
    trigger (close > high sebelumnya). Bar terakhir = bar entry (open)."""
    out, t, px = [], datetime(2025, 1, 1, tzinfo=timezone.utc), 1.0000
    for i in range(n_trend):
        o = px
        px += 0.0010
        out.append({"datetime": t.strftime("%Y-%m-%d %H:%M:%S"), "open": o, "high": px + 0.0003, "low": o - 0.0003, "close": px})
        t += timedelta(hours=4)
    for i in range(dip):                       # pullback: turun 0.0025 per bar
        o = px
        px -= 0.0025
        out.append({"datetime": t.strftime("%Y-%m-%d %H:%M:%S"), "open": o, "high": o + 0.0002, "low": px - 0.0003, "close": px})
        t += timedelta(hours=4)
    o = px                                     # trigger: close di atas high bar sebelumnya
    px += 0.0060
    out.append({"datetime": t.strftime("%Y-%m-%d %H:%M:%S"), "open": o, "high": px + 0.0002, "low": o - 0.0002, "close": px})
    t += timedelta(hours=4)
    out.append({"datetime": t.strftime("%Y-%m-%d %H:%M:%S"), "open": px, "high": px + 0.0005, "low": px - 0.0005, "close": px})
    return out


def test_signal_bull_after_pullback_and_trigger():
    bars = _uptrend_with_pullback()
    closes = [b["close"] for b in bars]
    e20, e50, e200 = ema_series(closes, 20), ema_series(closes, 50), ema_series(closes, 200)
    atr = atr_series(bars)
    i = len(bars) - 1
    sig = signal_at(bars, i, e20, e50, e200, atr, TPParams())
    assert sig is not None and sig["direction"] == "bull"
    assert sig["entry"] == bars[i]["open"]
    assert sig["sl"] < min(b["low"] for b in bars[i - 6:i])      # di bawah swing pullback + buffer
    assert 0.5 * sig["atr"] <= sig["risk"] <= 3 * sig["atr"]
    # tanpa trigger (close tidak menembus high sebelumnya) → tidak ada sinyal
    bars2 = [dict(b) for b in bars]
    bars2[i - 1]["close"] = bars2[i - 2]["high"] - 0.0001
    closes2 = [b["close"] for b in bars2]
    assert signal_at(bars2, i, ema_series(closes2, 20), ema_series(closes2, 50), ema_series(closes2, 200),
                     atr_series(bars2), TPParams()) is None


def test_engine_runs_and_hits_tp():
    bars = _uptrend_with_pullback()
    t = datetime.strptime(bars[-1]["datetime"], "%Y-%m-%d %H:%M:%S")
    px = bars[-1]["close"]
    for k in range(1, 30):                     # lanjut naik → TP 2R kena
        px += 0.0015
        bars.append({"datetime": (t + timedelta(hours=4 * k)).strftime("%Y-%m-%d %H:%M:%S"), "open": px - 0.0015,
                     "high": px + 0.0002, "low": px - 0.0017, "close": px})
    trades = run_pair("EUR/USD", "H4", bars, None, TPParams(tp_r=2.0))
    assert len(trades) >= 1
    tr = trades[0]
    assert tr["direction"] == "bull" and tr["legs"]["tpR"] == "tpR" and abs(tr["r"] - 2.0) < 1e-6
    assert tr["r_net"] < tr["r"]              # biaya spread terhitung
