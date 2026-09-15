"""POC pullback screener: profile, bias, stage, dedup key, formatter, Yahoo parser."""

from datetime import datetime, timedelta, timezone

from lib import state
from lib.poc import analyze_poc, build_profile, rule_grade_poc
from lib.telegram import format_poc_signal
from lib.yahoo import parse_chart


def _bars(path, start=datetime(2026, 6, 1, tzinfo=timezone.utc), step_hours=4, wick=0.0004,
          volume=None):
    """path = [(target, bars, vol_mult)] linear walk. volume=None → tanpa kolom volume."""
    out, t, price = [], start, path[0][0]
    for seg in path[1:]:
        target, bars = seg[0], seg[1]
        vmult = seg[2] if len(seg) > 2 else 1.0
        prev = price
        for i in range(1, bars + 1):
            nxt = price + (target - price) * i / bars
            # open dekat close bar sebelumnya (bukan awal segmen) supaya ATR realistis
            o, c = prev + (nxt - prev) * 0.1, nxt
            prev = nxt
            bar = {"datetime": t.strftime("%Y-%m-%d %H:%M:%S"), "open": o,
                   "high": max(o, c) + wick, "low": min(o, c) - wick, "close": c}
            if volume is not None:
                bar["volume"] = volume * vmult
            out.append(bar)
            t += timedelta(hours=step_hours)
        price = target
    return out


def bull_setup(pullback_to: float, volume=None, hold=3, pb_bars=6):
    """Struktur bullish: L1 1.0900 → H1 1.1100 → L2 1.1000 (HL) → impuls ke
    H2 1.1400 (HH, 16 bar, bagian tengah volume tebal) → pullback ke pullback_to."""
    pre = [(1.1000, 0), (1.0900, 8), (1.1100, 10), (1.1000, 8)]
    impulse = [(1.1150, 5, 1.0), (1.1250, 6, 4.0), (1.1400, 5, 1.0)]
    pb = [(pullback_to, pb_bars, 1.0), (pullback_to, hold, 1.0)]
    return _bars(pre + impulse + pb, volume=volume)


def test_profile_tpo_and_volume_poc_location():
    leg = _bars([(1.10, 0), (1.115, 5, 1.0), (1.125, 6, 4.0), (1.14, 5, 1.0)], volume=1000.0)
    p_vol = build_profile(leg, 40, 0.70)
    assert p_vol["source"] == "volume"
    assert 1.115 < p_vol["poc"] < 1.126          # bin tebal volume di tengah
    assert p_vol["val"] <= p_vol["poc"] <= p_vol["vah"]
    for c in leg:
        c.pop("volume")
    p_tpo = build_profile(leg, 40, 0.70)
    assert p_tpo["source"] == "tpo"
    assert p_tpo["leg_low"] < p_tpo["poc"] < p_tpo["leg_high"]


def test_bull_in_va_passes_pregrade_with_volume():
    candles = bull_setup(pullback_to=1.1230, volume=1000.0)
    cand = analyze_poc("AAPL", "D1", candles)
    assert cand is not None
    assert cand["bias"] == "bull" and cand["direction"] == "bull"
    assert cand["leg"]["bars"] >= 8
    assert cand["val"] <= cand["current_price"] <= cand["vah"]
    assert cand["stage"] == "in_va", cand["stage_label"]
    assert cand["pre_grade"] == "PASS", cand["pre_grade_reason"]
    assert cand["tps"]["tp1"] > cand["poc"] > cand["sl"]
    assert cand["rr"]["tp2"] > 1.5
    cand["htf_alignment"] = "aligned"
    cand["htf_timeframe"] = "1week"
    g = rule_grade_poc(cand)
    assert g["grade"] in ("A", "B")
    assert g["factors"]["profile"] == "A"


def test_tpo_profile_caps_grade_at_b():
    candles = bull_setup(pullback_to=1.1230)
    cand = analyze_poc("EUR/USD", "H4", candles)
    assert cand is not None and cand["profile"]["source"] == "tpo"
    cand["htf_alignment"] = "aligned"
    g = rule_grade_poc(cand)
    assert g["factors"]["profile"] == "B"
    assert g["grade"] == "B"


def test_stage_waiting_then_broken():
    # volume tebal di tengah leg → VA sempit → harga 1.1380 masih jauh dari VAH
    far = analyze_poc("EUR/USD", "H4", bull_setup(pullback_to=1.1380, volume=1000.0))
    assert far["stage"] == "waiting", (far["stage"], far["vah"])
    assert far["pre_grade"] == "FAIL" and "stage waiting" in far["pre_grade_reason"]
    # turun pelan (14 bar) supaya ATR tidak melonjak & pivot awal tidak terfilter
    broken = analyze_poc("EUR/USD", "H4", bull_setup(pullback_to=1.0980, pb_bars=14))
    assert broken["stage"] == "broken" and broken["pre_grade"] == "FAIL"


def test_confirmed_pullback_low_keeps_previous_leg():
    """D1 pivot 3/3: low pullback ikut terkonfirmasi jadi pivot L → leg tetap
    swing low awal impuls → swing high, bukan leg 3 bar dari pullback low."""
    cand = analyze_poc("AAPL", "D1", bull_setup(pullback_to=1.1230, volume=1000.0, hold=4))
    assert cand is not None
    assert abs(cand["leg"]["start_price"] - 1.0996) < 0.001
    assert abs(cand["leg"]["end_price"] - 1.1404) < 0.001
    assert cand["stage"] == "in_va"


def test_bear_mirror():
    path = [(1.1000, 0), (1.1100, 8), (1.0900, 10), (1.1000, 8),
            (1.0850, 5, 1.0), (1.0750, 6, 4.0), (1.0600, 5, 1.0), (1.0770, 6), (1.0770, 3)]
    cand = analyze_poc("GBP/USD", "H4", _bars(path))
    assert cand is not None and cand["bias"] == "bear" and cand["direction"] == "bear"
    assert cand["stage"] == "in_va"
    assert cand["sl"] > cand["poc"] > cand["tps"]["tp1"]


def test_unclear_structure_fails_pregrade():
    # HH tapi LL → range
    path = [(1.1000, 0), (1.0900, 8), (1.1100, 10), (1.0850, 8), (1.1150, 12), (1.1000, 6), (1.1000, 3)]
    cand = analyze_poc("EUR/USD", "H4", _bars(path))
    assert cand is None or (cand["bias"] is None and "UNCLEAR" in cand["pre_grade_reason"])


def test_dedup_key_per_leg_and_stage(monkeypatch):
    monkeypatch.delenv("UPSTASH_REDIS_REST_URL", raising=False)
    monkeypatch.delenv("UPSTASH_REDIS_REST_TOKEN", raising=False)
    state._redis = None
    state._memory.clear()
    cand = analyze_poc("BBCA.JK", "D1", bull_setup(pullback_to=1.1230, volume=5e6))
    assert not state.is_already_signaled(cand)
    state.mark_signaled(cand)
    assert state.is_already_signaled(cand)
    key = state.poc_key("BBCA.JK", "D1", cand["leg_date"], "in_va")
    assert key.startswith("poc:BBCA.JK:D1:2026") and key in state._memory
    other = dict(cand, stage="reacted")
    assert not state.is_already_signaled(other)


def test_format_poc_signal_text_only():
    cand = analyze_poc("AAPL", "D1", bull_setup(pullback_to=1.1230, volume=1000.0))
    cand["htf_alignment"] = "neutral"
    cand["htf_timeframe"] = "1week"
    rule_grade_poc(cand)
    msg = format_poc_signal(cand)
    assert "AAPL — POC PULLBACK BUY on D1" in msg
    assert "LONG" in msg and "POC:" in msg and "VAH" in msg and "VAL" in msg
    assert "SL konservatif" in msg and "TP1" in msg and "R:R" in msg
    assert "Analisis edukatif" in msg
    assert "<img" not in msg


def test_yahoo_parse_chart_skips_null_and_formats_daily():
    data = {"chart": {"result": [{
        "meta": {"exchangeTimezoneName": "Asia/Jakarta"},
        "timestamp": [int(datetime(2026, 9, d, tzinfo=timezone.utc).timestamp()) for d in (10, 11, 12)],
        "indicators": {"quote": [{"open": [100, None, 102], "high": [101, None, 103],
                                  "low": [99, None, 101], "close": [100.5, None, 102.5],
                                  "volume": [1000, None, 3000]}]},
    }], "error": None}}
    out = parse_chart(data, "1day")
    assert [c["datetime"] for c in out] == ["2026-09-10", "2026-09-12"]
    assert out[1]["volume"] == 3000.0 and out[1]["close"] == 102.5


def test_scanner_sends_poc_in_dry_run(monkeypatch, capsys):
    """run_scan: POC pullback dari candle yang sama, HTF lazy, dry-run tidak mark."""
    from lib import scanner

    class FakeTD:
        def __init__(self, *a, **k):
            self.request_count = 0

        def get_candles(self, symbol, interval, outputsize=200, retries=2):
            self.request_count += 1
            if interval == "1week":  # HTF uptrend → aligned
                return [{"datetime": f"2026-01-{i % 28 + 1:02d}", "open": 1, "high": 1,
                         "low": 1, "close": 1 + i * 0.002} for i in range(80)]
            return bull_setup(pullback_to=1.1230, volume=1000.0)

    monkeypatch.setenv("GRADER", "rule")
    monkeypatch.delenv("UPSTASH_REDIS_REST_URL", raising=False)
    monkeypatch.delenv("UPSTASH_REDIS_REST_TOKEN", raising=False)
    state._redis = None
    state._memory.clear()
    monkeypatch.setattr(scanner, "TwelveDataClient", FakeTD)
    monkeypatch.setattr(scanner, "YahooClient", FakeTD)
    monkeypatch.setattr(scanner, "is_forex_closed", lambda now=None: False)
    sent = []
    monkeypatch.setattr(scanner, "send_poc_signal", lambda c, candles=None: sent.append(c["pair"]))
    assert scanner.run_scan("D1", pairs=["AAPL"], dry_run=True) == 0
    out = capsys.readouterr().out
    assert "[dry_run] Would send: AAPL POC bull [in_va] Grade" in out
    assert sent == [] and not state._memory
    assert scanner.run_scan("D1", pairs=["AAPL"], dry_run=False) == 0
    assert sent == ["AAPL"]
    assert scanner.run_scan("D1", pairs=["AAPL"], dry_run=False) == 0
    assert sent == ["AAPL"]  # dedup


def test_poc_compact_and_chart(monkeypatch):
    from lib import telegram
    from lib.chart_poc import render_poc_chart
    from lib.telegram import format_poc_compact
    candles = bull_setup(pullback_to=1.1230, volume=1000.0)
    cand = analyze_poc("AAPL", "D1", candles)
    cand["htf_alignment"] = "neutral"; cand["htf_timeframe"] = "1week"
    rule_grade_poc(cand)
    msg = format_poc_compact(cand)
    for key in ("Zona:", "Entry:", "SL:", "TP1:", "TP2:", "LONG"):
        assert key in msg
    assert "TP3" not in msg and "Reasoning" not in msg and len(msg) < 1024
    png = render_poc_chart(cand, candles)
    assert png[:8] == b"\x89PNG\r\n\x1a\n" and len(png) > 15_000
    calls = []
    monkeypatch.delenv("SIGNAL_VERBOSE", raising=False)
    monkeypatch.setattr(telegram, "send_photo", lambda png, cap: calls.append(("photo", cap)))
    monkeypatch.setattr(telegram, "send_message", lambda text: calls.append(("text", text)))
    telegram.send_poc_signal(cand, candles)
    assert [k for k, _ in calls] == ["photo"] and "POC PULLBACK" in calls[0][1]
    calls.clear()
    telegram.send_poc_signal(cand)
    assert [k for k, _ in calls] == ["text"]
