"""Filter konflik antar-timeframe (lib/mtf.py) + integrasi rule grade & scanner."""

from config import settings
from lib import scanner, state
from lib.grading import rule_grade
from lib.mtf import attach_mtf, ltf_bias
from lib.scanner import analyze_candles
from tests.fixtures import synthetic_bat
from tests.test_poc import _bars


def bear_structure():
    """LH + LL: 1.20 → 1.17 → 1.19 (LH) → 1.15 (LL) → 1.165."""
    return _bars([(1.20, 0), (1.17, 12), (1.19, 12), (1.15, 12), (1.165, 8), (1.165, 6)])


def bull_structure():
    return _bars([(1.10, 0), (1.13, 12), (1.11, 12), (1.15, 12), (1.135, 8), (1.135, 6)])


def test_ltf_bias_detects_structure():
    assert ltf_bias(bear_structure()) == "bear"
    assert ltf_bias(bull_structure()) == "bull"
    assert ltf_bias(bear_structure()[:20]) is None      # data kurang → tidak tahu


def test_attach_mtf_and_grade_factor(monkeypatch):
    cand = [c for c in analyze_candles("EUR/USD", "H4", synthetic_bat(projected=True)) if c["d_projected"]][0]
    cand["htf_alignment"] = "aligned"
    monkeypatch.setattr(settings, "MTF_CONFLICT_FILTER", False)
    monkeypatch.setattr(settings, "MTF_OWN_TREND", False)
    m = attach_mtf(cand, synthetic_bat(projected=True), bear_structure(), "H4")
    assert m["ltf_tf"] == "1h" and m["ltf_bias"] == "bear" and m["conflict_ltf"] and m["conflict"]
    assert "mtf" not in rule_grade(cand)["factors"]           # filter mati → faktor tidak dipakai
    monkeypatch.setattr(settings, "MTF_CONFLICT_FILTER", True)
    assert rule_grade(cand)["factors"]["mtf"] == "C" and cand["rule_grade"]["grade"] == "C"
    attach_mtf(cand, synthetic_bat(projected=True), bull_structure(), "H4")
    assert rule_grade(cand)["factors"]["mtf"] == "A"
    attach_mtf(cand, synthetic_bat(projected=True), [], "H4")       # LTF tidak tersedia → tidak konflik
    assert cand["mtf"]["ltf_bias"] is None and not cand["mtf"]["conflict"]


def test_own_trend_option(monkeypatch):
    cand = [c for c in analyze_candles("EUR/USD", "H4", synthetic_bat(projected=True)) if c["d_projected"]][0]
    # Bull Bat sintetis: harga sedang turun ke PRZ → EMA20/50 TF sendiri "down" = konflik hanya kalau opsi aktif
    monkeypatch.setattr(settings, "MTF_OWN_TREND", False)
    m = attach_mtf(cand, synthetic_bat(projected=True), [], "H4")
    assert m["own_trend"] in ("down", "neutral", "up")
    if m["conflict_own"]:
        assert not m["conflict"]
        monkeypatch.setattr(settings, "MTF_OWN_TREND", True)
        assert attach_mtf(cand, synthetic_bat(projected=True), [], "H4")["conflict"]


class _TD:
    ltf: list = []

    def __init__(self, api_key: str, min_interval=None):
        self.request_count = 0

    def get_candles(self, symbol, interval, outputsize=200, retries=2):
        self.request_count += 1
        if interval in ("1day", "1week"):
            return [{"datetime": f"2026-01-{i % 28 + 1:02d}", "open": 1, "high": 1, "low": 1, "close": 1 + i * 0.002}
                    for i in range(80)]
        if interval == "1h":
            return list(self.ltf)
        return synthetic_bat(projected=True)


def test_scanner_conflict_blocks_signal(monkeypatch, capsys):
    monkeypatch.setenv("TWELVEDATA_API_KEY", "x")
    monkeypatch.setenv("GRADER", "rule")
    monkeypatch.delenv("UPSTASH_REDIS_REST_URL", raising=False)
    monkeypatch.delenv("UPSTASH_REDIS_REST_TOKEN", raising=False)
    state._redis = None
    state._memory.clear()
    monkeypatch.setattr(scanner, "TwelveDataClient", _TD)
    monkeypatch.setattr(scanner, "is_forex_closed", lambda now=None: False)
    monkeypatch.setattr(settings, "POC_ENABLED", False)
    monkeypatch.setattr(settings, "MTF_CONFLICT_FILTER", True)
    monkeypatch.setattr(settings, "MTF_OWN_TREND", False)
    sent = []
    monkeypatch.setattr(scanner, "send_signal", lambda c, g, candles=None: sent.append(c["pair"]))
    _TD.ltf = bear_structure()                       # H1 LH/LL melawan Bat bull H4
    assert scanner.run_scan("H4", pairs=["EUR/USD"], dry_run=False) == 0
    out = capsys.readouterr().out
    assert "[mtf-conflict] EUR/USD Bat bull" in out and sent == []
    state._memory.clear()
    _TD.ltf = bull_structure()                       # searah → terkirim
    assert scanner.run_scan("H4", pairs=["EUR/USD"], dry_run=False) == 0
    assert sent == ["EUR/USD"]
