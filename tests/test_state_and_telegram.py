import os

from lib import state
from lib.scanner import analyze_candles, is_forex_closed
from lib.telegram import format_signal
from tests.fixtures import synthetic_bat
from datetime import datetime, timezone


def test_memory_state_roundtrip(monkeypatch):
    monkeypatch.delenv("UPSTASH_REDIS_REST_URL", raising=False)
    monkeypatch.delenv("UPSTASH_REDIS_REST_TOKEN", raising=False)
    state._redis = None
    state._memory.clear()
    c = analyze_candles("EUR/USD", "H4", synthetic_bat())[0]
    assert state.backend_name() == "memory"
    assert not state.is_already_signaled(c)
    state.mark_signaled(c)
    assert state.is_already_signaled(c)
    assert state.signal_key("EUR/USD", "H4", "Deep Crab", "20260601") == "signal:EUR_USD:H4:DeepCrab:20260601"


def test_format_signal_contains_levels():
    c = analyze_candles("EUR/USD", "H4", synthetic_bat())[0]
    c["htf_alignment"] = "aligned"
    grade = {"grade": "A", "reasoning": ["Bat rapi <2%", "HTF aligned"], "entry_model": "Scaled",
             "invalidation": "close < X", "warnings": ["NFP Jumat"], "source": "claude"}
    msg = format_signal(c, grade)
    assert "EUR/USD" in msg and "Bat BULL" in msg
    assert "TP1" in msg and "SL" in msg and "Grade: <b>A</b>" in msg
    assert "NFP" in msg
    assert "Analisis edukatif" in msg


def test_forex_closed_schedule():
    assert is_forex_closed(datetime(2026, 9, 12, 10, tzinfo=timezone.utc))      # Sabtu
    assert is_forex_closed(datetime(2026, 9, 13, 10, tzinfo=timezone.utc))      # Minggu pagi
    assert not is_forex_closed(datetime(2026, 9, 13, 23, tzinfo=timezone.utc))  # Minggu 23 UTC
    assert is_forex_closed(datetime(2026, 9, 11, 23, tzinfo=timezone.utc))      # Jumat 23 UTC
    assert not is_forex_closed(datetime(2026, 9, 9, 12, tzinfo=timezone.utc))   # Rabu
