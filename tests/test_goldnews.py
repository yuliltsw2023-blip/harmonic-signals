from datetime import date, datetime, timezone

from goldnews.sessions import classify, due_slots, session_window, slot_id
from goldnews.telegram import format_briefing

UTC = timezone.utc


def keys(now):
    return [s.key for s, _ in due_slots(now)]


def test_slots_winter():
    # 18 Nov 2026 (Rabu) — London & NY sudah musim dingin
    assert keys(datetime(2026, 11, 17, 23, 30, tzinfo=UTC)) == ["pre_asia"]      # 06:30 WIB
    assert keys(datetime(2026, 11, 18, 7, 25, tzinfo=UTC)) == ["pre_london"]     # 14:25 WIB
    assert keys(datetime(2026, 11, 18, 12, 20, tzinfo=UTC)) == ["pre_ny"]        # 19:20 WIB
    assert keys(datetime(2026, 11, 18, 14, 0, tzinfo=UTC))[0] == "post_us"       # 21:00 WIB
    assert keys(datetime(2026, 11, 18, 3, 0, tzinfo=UTC)) == []


def test_slots_summer_shift_one_hour():
    # Juli: London BST, NY EDT → slot 1 jam lebih awal dalam WIB
    assert keys(datetime(2026, 7, 15, 6, 30, tzinfo=UTC)) == ["pre_london"]      # 13:30 WIB
    assert keys(datetime(2026, 7, 15, 11, 30, tzinfo=UTC)) == ["pre_ny"]         # 18:30 WIB


def test_weekend():
    assert keys(datetime(2026, 11, 20, 23, 30, tzinfo=UTC)) == ["weekly"]        # Sabtu 06:30 WIB
    assert keys(datetime(2026, 11, 21, 23, 30, tzinfo=UTC)) == []                # Minggu
    assert keys(datetime(2026, 11, 22, 23, 30, tzinfo=UTC)) == ["pre_asia"]      # Senin 06:30 WIB


def test_slot_id_uses_wib_date():
    s, t = due_slots(datetime(2026, 11, 17, 23, 30, tzinfo=UTC))[0]
    assert slot_id(s, t) == "2026-11-18_pre_asia"


def test_session_windows_winter():
    a, b = session_window("london", date(2026, 11, 18))
    assert (a.hour, b.hour) == (8, 13)
    a, b = session_window("ny", date(2026, 11, 18))
    assert (a.hour, b.hour) == (13, 22)


def test_classify():
    assert classify(100, 112, 99, 111, 20) == "bullish"
    assert classify(100, 101, 88, 89, 20) == "bearish"
    assert classify(100, 103, 97, 101, 20) == "sideways"           # gerak kecil
    assert classify(100, 120, 85, 105, 20) == "sideways"           # naik tapi close tengah


def test_format_briefing_short():
    rep = {
        "slot_label": "Pra-London", "t": 1795000000, "target_label": "Sesi London",
        "price": {"last": 3766.8},
        "sessions": [{"name": "Asia", "complete": True, "label": "bullish", "change": 12.3,
                      "range": 20.0, "range_vs_adr": 0.4}],
        "prev_eval": None,
        "key_news": [{"t": 1795000000, "title": "Gold <rises>", "effect": "bullish", "why": "dolar melemah"}],
        "analysis": {"headline": "Emas menguat", "bias": {"direction": "bearish", "confidence": "sedang",
                                                           "reason": "x"},
                     "event_risks": [], "levels": {"support": [3750.0], "resistance": [3780.0]},
                     "scenarios": [{"if_": "a", "then": "b"}]},
    }
    txt = format_briefing(rep, "https://x/#r=1")
    assert "&lt;rises&gt;" in txt and "BEARISH" in txt and len(txt) < 4000


# ---------------------------------------------------------------- rencana trading
from goldnews.trade import evaluate, validate  # noqa: E402


def _plan(**kw):
    p = {"style": "intraday", "action": "sell", "order": "limit", "entry": 3775.0, "sl": 3792.0,
         "tp1": 3757.0, "tp2": 3742.0, "valid_hours": 2, "invalidation": "x", "reason": "y"}
    p.update(kw)
    return p


def test_validate_ok_and_rr():
    p = validate(_plan(), price=3765.0, atr_entry=10.0, atr_h1=20.0)
    assert p["action"] == "sell" and p["tf"] == "M15" and p["rr1"] > 1


def test_validate_rejects_wrong_side():
    p = validate(_plan(sl=3760.0), price=3765.0, atr_entry=10.0, atr_h1=20.0)
    assert p["action"] == "no_trade" and "SELL" in p["rejected"]


def test_validate_fixes_order_type():
    # SELL di bawah harga = stop, bukan limit
    p = validate(_plan(entry=3760.0, sl=3775.0, tp1=3745.0, tp2=3730.0), price=3765.0, atr_entry=10.0, atr_h1=20.0)
    assert p["order"] == "stop"


def test_evaluate_sell_tp1_and_sl_first():
    p = validate(_plan(), price=3765.0, atr_entry=10.0, atr_h1=20.0)
    t0 = 1_000_000
    bars = [[t0 + 300, 3765, 3776, 3764, 3770],      # terisi di 3775
            [t0 + 600, 3770, 3771, 3756, 3758]]      # kena TP1
    assert evaluate(p, t0, bars, t0 + 900)["result"] == "tp1"
    bars2 = [[t0 + 300, 3765, 3776, 3764, 3770], [t0 + 600, 3770, 3793, 3756, 3760]]
    assert evaluate(p, t0, bars2, t0 + 900)["result"] == "sl"   # SL & TP satu bar → SL


def test_evaluate_not_filled():
    p = validate(_plan(), price=3765.0, atr_entry=10.0, atr_h1=20.0)
    t0 = 1_000_000
    bars = [[t0 + i * 300, 3765, 3770, 3760, 3765] for i in range(1, 40)]
    assert evaluate(p, t0, bars, t0 + 40 * 300)["result"] == "not_filled"


def test_market_open_weekend_filter():
    from goldnews.sources import market_open
    ts = lambda *a: int(datetime(*a, tzinfo=UTC).timestamp())
    assert market_open(ts(2026, 11, 20, 20, 0))        # Jumat 15:00 NY
    assert not market_open(ts(2026, 11, 20, 23, 0))    # Jumat 18:00 NY = tutup
    assert not market_open(ts(2026, 11, 22, 13, 0))    # Minggu siang
    assert market_open(ts(2026, 11, 22, 23, 5))        # Minggu 18:05 NY = buka
    assert not market_open(ts(2026, 11, 23, 22, 30))   # jeda harian 17:30 NY


# ---------------------------------------------------------------- SMC
from goldnews import smc  # noqa: E402


def test_validate_gates_incomplete_checklist():
    chk = {"sell": {"liquidity": {"t": 1}, "structure": {"t": 2}, "poi": None, "confirmation": None,
                    "stale": [], "complete": False}}
    p = validate(_plan(), price=3765.0, atr_entry=10.0, atr_h1=20.0, checks=chk)
    assert p["action"] == "wait_sell" and "poi" in p["gated"]
    assert evaluate(p, 1_000_000, [[1_000_300, 3765, 3800, 3700, 3760]], 1_100_000) is None


def _zigzag(points, step=300, t0=1_000_000):
    """Candle 5m mengikuti titik harga (open→close garis lurus antar titik)."""
    bars, t = [], t0
    for a, b in zip(points, points[1:]):
        n = 6
        for i in range(n):
            o = a + (b - a) * i / n
            c = a + (b - a) * (i + 1) / n
            bars.append([t, o, max(o, c) + 0.2, min(o, c) - 0.2, c])
            t += step
    return bars


def test_structure_bos_and_choch():
    # naik HH/HL lalu jatuh tembus HL terakhir → CHoCH/MSS bear
    bars = _zigzag([100, 110, 105, 115, 108, 120, 112, 125, 100, 95])
    trend, events, labeled = smc.structure(bars, 2, smc.atr(bars))
    kinds = [(e.kind, e.dir) for e in events]
    assert ("BOS", "bull") in kinds
    assert any(d == "bear" and k in ("CHoCH", "MSS") for k, d in kinds)
    assert trend == "bear"


def test_liquidity_sweep_detected():
    bars = _zigzag([100, 110, 104, 109, 103, 108])
    # wick menembus swing high 110 lalu close kembali di bawah
    t = bars[-1][0] + 300
    bars += [[t, 108, 111.5, 107, 108.5], [t + 300, 108.5, 109, 106, 107], [t + 600, 107, 108, 105, 106]]
    sweeps, pools = smc.liquidity(bars, 2, smc.atr(bars), {}, 10)
    assert any(s[2] == "BSL" and abs(s[3] - 110.2) < 0.5 for s in sweeps)
