"""End-to-end run_scan() tanpa network: Twelve Data di-mock, GRADER=rule,
Telegram di-mock. Memastikan alur pre-grade → dedup → HTF → grade → send."""

from datetime import datetime, timezone

from lib import scanner, state
from tests.fixtures import synthetic_bat, synthetic_random_walk


class FakeTD:
    def __init__(self, api_key: str, min_interval=None):
        self.request_count = 0

    def get_candles(self, symbol, interval, outputsize=200, retries=2):
        self.request_count += 1
        if interval in ("1day", "1week"):
            # HTF uptrend → bull pattern aligned
            return [{"datetime": f"2026-01-{i % 28 + 1:02d}", "open": 1, "high": 1,
                     "low": 1, "close": 1 + i * 0.002} for i in range(80)]
        if symbol == "EUR/USD":
            return synthetic_bat(bull=True, projected=True)
        return synthetic_random_walk(200, seed=3)


def _setup(monkeypatch):
    monkeypatch.setenv("TWELVEDATA_API_KEY", "x")
    monkeypatch.setenv("GRADER", "rule")
    monkeypatch.delenv("UPSTASH_REDIS_REST_URL", raising=False)
    monkeypatch.delenv("UPSTASH_REDIS_REST_TOKEN", raising=False)
    state._redis = None
    state._memory.clear()
    monkeypatch.setattr(scanner, "TwelveDataClient", FakeTD)
    # paksa market buka
    monkeypatch.setattr(scanner, "is_forex_closed", lambda now=None: False)


def test_dry_run_does_not_send_or_mark(monkeypatch, capsys):
    _setup(monkeypatch)
    sent = []
    monkeypatch.setattr(scanner, "send_signal", lambda c, g, candles=None: sent.append(c))
    rc = scanner.run_scan("H4", pairs=["EUR/USD", "GBP/USD"], dry_run=True)
    out = capsys.readouterr().out
    assert rc == 0
    assert "[dry_run] Would send: EUR/USD Bat bull" in out
    assert sent == []
    assert not state._memory


def test_live_sends_once_then_dedups(monkeypatch):
    _setup(monkeypatch)
    sent = []
    monkeypatch.setattr(scanner, "send_signal", lambda c, g, candles=None: sent.append((c["pair"], g["grade"])))
    assert scanner.run_scan("H4", pairs=["EUR/USD"], dry_run=False) == 0
    assert sent == [("EUR/USD", "A")]
    assert scanner.run_scan("H4", pairs=["EUR/USD"], dry_run=False) == 0
    assert len(sent) == 1  # kedua kali kena dedup


def test_all_pairs_error_returns_1(monkeypatch):
    _setup(monkeypatch)

    class Broken(FakeTD):
        def get_candles(self, *a, **k):
            raise RuntimeError("api down")

    monkeypatch.setattr(scanner, "TwelveDataClient", Broken)
    assert scanner.run_scan("H4", pairs=["EUR/USD", "GBP/USD"], dry_run=True) == 1


def test_weekend_skip(monkeypatch):
    monkeypatch.setenv("TWELVEDATA_API_KEY", "x")
    monkeypatch.setattr(scanner, "is_forex_closed", lambda now=None: True)
    assert scanner.run_scan("H4", pairs=["EUR/USD"], dry_run=True) == 0
