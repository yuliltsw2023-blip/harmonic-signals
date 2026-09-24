"""Aturan eksekusi 24 Sep 2026: closed-candle, mode confirmed (harmonic & POC),
ID setup per C, gate grade/sesi, cancel POC saat struktur patah."""

from datetime import datetime, timedelta, timezone

from config import settings
from lib import scanner, state
from lib.exec_rules import exec_grade_ok, harmonic_confirmed, poc_confirmed, session_ok, split_closed
from lib.orders import harmonic_event, poc_event, setup_id
from lib.poc import analyze_poc
from lib.scanner import analyze_candles
from tests.fixtures import synthetic_bat
from tests.test_poc import _bars, bull_setup


def _completed_bat():
    cands = [c for c in analyze_candles("EUR/USD", "H4", synthetic_bat(projected=False)) if not c["d_projected"]]
    assert cands, "fixture completed Bat harus terdeteksi"
    return cands[0]


# ---------------------------------------------------------------- closed candle
def test_split_closed_drops_running_bar():
    candles = [{"datetime": "2026-09-24 03:00:00", "open": 1, "high": 1, "low": 1, "close": 1},
               {"datetime": "2026-09-24 04:00:00", "open": 1, "high": 1, "low": 1, "close": 1}]
    now = datetime(2026, 9, 24, 4, 1, tzinfo=timezone.utc)
    closed, forming = split_closed(candles, "1h", now)
    assert len(closed) == 1 and forming["datetime"] == "2026-09-24 04:00:00"
    closed, forming = split_closed(candles, "1h", now + timedelta(hours=1))
    assert len(closed) == 2 and forming is None
    # daily: bar hari ini masih berjalan
    daily = [{"datetime": "2026-09-23", "open": 1, "high": 1, "low": 1, "close": 1},
             {"datetime": "2026-09-24", "open": 1, "high": 1, "low": 1, "close": 1}]
    closed, forming = split_closed(daily, "1day", datetime(2026, 9, 24, 0, 1, tzinfo=timezone.utc))
    assert len(closed) == 1 and forming["datetime"] == "2026-09-24"


# ---------------------------------------------------------------- harmonic confirmed
def test_harmonic_confirmed_needs_completed_d(monkeypatch):
    monkeypatch.setattr(settings, "MIN_RR_TP2_PREGRADE", 2.0)
    proj = [c for c in analyze_candles("EUR/USD", "H4", synthetic_bat(projected=True)) if c["d_projected"]][0]
    assert harmonic_confirmed(proj, synthetic_bat(projected=True)) is False


def test_harmonic_confirmed_levels_and_run_limit(monkeypatch):
    monkeypatch.setattr(settings, "MIN_RR_TP2_PREGRADE", 0.5)
    candles = synthetic_bat(projected=False)
    cand = _completed_bat()
    assert harmonic_confirmed(cand, candles) is True
    ex = cand["exec"]
    D, A = cand["points"]["D"]["price"], cand["points"]["A"]["price"]
    assert ex["order"] == "market" and ex["entry"] == cand["current_price"]
    assert ex["sl"] < D                                             # SL di luar D, bukan X
    assert ex["sl"] > cand["sl"]                                    # lebih dekat dari SL beyond X
    assert abs(ex["tps"]["tp1"] - (D + 0.382 * (A - D))) < 1e-9
    assert 0 <= ex["run_ad"] <= settings.CONFIRM_MAX_RUN_AD
    # harga sudah lari terlalu jauh dari D → tidak dieksekusi
    far = dict(cand, current_price=D + 0.5 * (A - D))
    assert harmonic_confirmed(far, candles) is False
    # harga menembus D → tidak dieksekusi
    below = dict(cand, current_price=D - 0.001)
    assert harmonic_confirmed(below, candles) is False


def test_harmonic_confirmed_rr_gate(monkeypatch):
    monkeypatch.setattr(settings, "MIN_RR_TP2_PREGRADE", 50.0)
    cand = _completed_bat()
    assert harmonic_confirmed(cand, synthetic_bat(projected=False)) is False
    assert cand["exec_reject"].startswith("R:R confirmed")


# ---------------------------------------------------------------- POC confirmed
def _poc_reacted(pullback_to=1.1200):
    """Pullback ke area POC lalu candle bullish engulfing yang close di atas POC."""
    candles = bull_setup(pullback_to=pullback_to, volume=1000.0, hold=1)
    last = candles[-1]
    t = datetime.strptime(last["datetime"], "%Y-%m-%d %H:%M:%S")
    bear = {"datetime": (t + timedelta(hours=4)).strftime("%Y-%m-%d %H:%M:%S"), "open": pullback_to + 0.0010,
            "high": pullback_to + 0.0012, "low": pullback_to - 0.0004, "close": pullback_to - 0.0002, "volume": 1000.0}
    bull = {"datetime": (t + timedelta(hours=8)).strftime("%Y-%m-%d %H:%M:%S"), "open": pullback_to - 0.0003,
            "high": pullback_to + 0.0060, "low": pullback_to - 0.0005, "close": pullback_to + 0.0055, "volume": 1000.0}
    return candles + [bear, bull]


def test_poc_confirmed_after_touch_and_reaction(monkeypatch):
    monkeypatch.setattr(settings, "MIN_RR_TP2_PREGRADE", 2.0)
    candles = _poc_reacted()
    cand = analyze_poc("AAPL", "D1", candles)
    assert cand is not None and cand["stage"] in ("in_va", "reacted")
    assert cand["reactions"], "candle terakhir harus terbaca sebagai reaksi"
    assert poc_confirmed(cand, candles) is True
    ex = cand["exec"]
    assert ex["order"] == "market" and ex["entry"] == candles[-1]["close"]
    assert ex["sl"] < cand["pullback_extreme"] and ex["sl"] < cand["val"]
    assert ex["rr"]["tp2"] >= 2.0


def test_poc_confirmed_rejects_without_reaction_or_touch(monkeypatch):
    monkeypatch.setattr(settings, "MIN_RR_TP2_PREGRADE", 2.0)
    # pullback dangkal (hanya ke VAH) tanpa reaksi → tidak dieksekusi
    candles = bull_setup(pullback_to=1.1300, volume=1000.0)
    cand = analyze_poc("AAPL", "D1", candles)
    assert cand is not None
    assert poc_confirmed(cand, candles) is False


# ---------------------------------------------------------------- id & gate
def test_setup_id_by_c_date(monkeypatch):
    cand = _completed_bat()
    assert cand["c_date"] != cand["d_date"]
    monkeypatch.setattr(settings, "SETUP_ID_BY_C", True)
    assert setup_id(cand).endswith(cand["c_date"])
    assert state._key(cand).split(":")[4] == cand["c_date"]
    monkeypatch.setattr(settings, "SETUP_ID_BY_C", False)
    assert setup_id(cand).endswith(cand["d_date"])


def test_event_uses_exec_levels(monkeypatch):
    monkeypatch.setattr(settings, "MIN_RR_TP2_PREGRADE", 0.5)
    cand = _completed_bat()
    assert harmonic_confirmed(cand, synthetic_bat(projected=False))
    ev = harmonic_event(cand, {"grade": "A"})
    assert ev["order"] == "market" and ev["exec_mode"] == "confirmed"
    assert ev["entry"] == cand["exec"]["entry"] and ev["sl"] == cand["exec"]["sl"]
    plain = harmonic_event({k: v for k, v in cand.items() if k != "exec"}, {"grade": "A"})
    assert plain["order"] == "limit" and plain["entry"] == cand["entry"]


def test_exec_grade_and_session_gate(monkeypatch):
    monkeypatch.setattr(settings, "EXEC_MIN_GRADE", "A")
    assert exec_grade_ok("A") and not exec_grade_ok("B") and not exec_grade_ok(None)
    monkeypatch.setattr(settings, "EXEC_MIN_GRADE", "B")
    assert exec_grade_ok("B") and not exec_grade_ok("C")
    monkeypatch.setattr(settings, "EXEC_SESSION_UTC", (6, 20))
    assert session_ok("EUR/USD", "H1", datetime(2026, 9, 24, 8, tzinfo=timezone.utc))
    assert not session_ok("EUR/USD", "H4", datetime(2026, 9, 24, 1, tzinfo=timezone.utc))
    assert session_ok("EUR/USD", "D1", datetime(2026, 9, 24, 1, tzinfo=timezone.utc))      # D1 tidak difilter
    assert session_ok("BTC/USD", "H1", datetime(2026, 9, 24, 1, tzinfo=timezone.utc))      # crypto 24/7
    monkeypatch.setattr(settings, "EXEC_SESSION_UTC", ())
    assert session_ok("EUR/USD", "H1", datetime(2026, 9, 24, 1, tzinfo=timezone.utc))


# ---------------------------------------------------------------- scanner end-to-end
class _TD:
    data: dict = {}

    def __init__(self, api_key: str, min_interval=None):
        self.request_count = 0

    def get_candles(self, symbol, interval, outputsize=200, retries=2):
        self.request_count += 1
        if interval in ("1day", "1week"):
            return [{"datetime": f"2026-01-{i % 28 + 1:02d}", "open": 1, "high": 1, "low": 1, "close": 1 + i * 0.002}
                    for i in range(80)]
        return list(self.data[symbol])


def _live(monkeypatch, **overrides):
    monkeypatch.setenv("TWELVEDATA_API_KEY", "x")
    monkeypatch.setenv("GRADER", "rule")
    monkeypatch.setenv("MT5_QUEUE", "true")
    monkeypatch.delenv("UPSTASH_REDIS_REST_URL", raising=False)
    monkeypatch.delenv("UPSTASH_REDIS_REST_TOKEN", raising=False)
    state._redis = None
    state._memory.clear()
    state._queue.clear()
    monkeypatch.setattr(scanner, "TwelveDataClient", _TD)
    monkeypatch.setattr(scanner, "is_forex_closed", lambda now=None: False)
    monkeypatch.setattr(scanner, "send_signal", lambda c, g, candles=None: None)
    monkeypatch.setattr(scanner, "send_poc_signal", lambda c, candles=None: None)
    sent = []
    monkeypatch.setattr(scanner, "send_message", lambda text, parse_mode="HTML": sent.append(text))
    for k, v in overrides.items():
        monkeypatch.setattr(settings, k, v)
    return sent


def _queued():
    import json
    return [json.loads(x) for x in state._queue]


def test_scanner_confirmed_mode_queues_market_once(monkeypatch, capsys):
    sent = _live(monkeypatch, HARMONIC_EXEC_MODE="confirmed", POC_EXEC_MODE="confirmed", EXEC_MIN_GRADE="B",
                 MIN_RR_TP2_PREGRADE=0.5, POC_ENABLED=False, EXEC_SESSION_UTC=())
    _TD.data = {"EUR/USD": synthetic_bat(projected=False)}
    assert scanner.run_scan("H4", pairs=["EUR/USD"], dry_run=False) == 0
    evs = [e for e in _queued() if e["action"] == "place"]
    assert len(evs) == 1 and evs[0]["order"] == "market" and evs[0]["exec_mode"] == "confirmed"
    assert any("ENTRY CONFIRMED" in t for t in sent)
    assert "[exec-confirmed]" in capsys.readouterr().out
    # scan kedua: dedup stage 'confirmed' → tidak ada event baru
    assert scanner.run_scan("H4", pairs=["EUR/USD"], dry_run=False) == 0
    assert len([e for e in _queued() if e["action"] == "place"]) == 1


def test_scanner_limit_mode_respects_min_grade(monkeypatch, capsys):
    _live(monkeypatch, HARMONIC_EXEC_MODE="limit", POC_EXEC_MODE="limit", EXEC_MIN_GRADE="A", POC_ENABLED=False)
    _TD.data = {"EUR/USD": synthetic_bat(projected=True)}
    # HTF fixture uptrend → Bat sintetis Grade A → masuk antrean limit
    assert scanner.run_scan("H4", pairs=["EUR/USD"], dry_run=False) == 0
    evs = [e for e in _queued() if e["action"] == "place"]
    assert len(evs) == 1 and evs[0]["order"] == "limit" and evs[0]["grade"] == "A"


def test_scanner_poc_cancel_on_structure_break(monkeypatch, capsys):
    _live(monkeypatch, HARMONIC_EXEC_MODE="limit", POC_EXEC_MODE="limit", EXEC_MIN_GRADE="B", POC_ENABLED=True,
          POC_CANCEL_ON_STAGE=("broken", "continued", "left_va", "below_va"))
    base = bull_setup(pullback_to=1.1230, volume=1000.0)   # profile volume → depth ideal
    _TD.data = {"NZD/USD": base}
    assert scanner.run_scan("H4", pairs=["NZD/USD"], dry_run=False) == 0
    place = [e for e in _queued() if e["action"] == "place" and e["kind"] == "poc"]
    assert len(place) == 1
    # harga runtuh di bawah awal leg → stage broken → cancel sekali
    t = datetime.strptime(base[-1]["datetime"], "%Y-%m-%d %H:%M:%S")
    crash = [{"datetime": (t + timedelta(hours=4 * (i + 1))).strftime("%Y-%m-%d %H:%M:%S"),
              "open": 1.10 - 0.002 * i, "high": 1.10 - 0.002 * i + 0.0005, "low": 1.09 - 0.002 * i,
              "close": 1.095 - 0.002 * i, "volume": 1000.0} for i in range(3)]
    _TD.data = {"NZD/USD": base + crash}
    assert scanner.run_scan("H4", pairs=["NZD/USD"], dry_run=False) == 0
    assert scanner.run_scan("H4", pairs=["NZD/USD"], dry_run=False) == 0
    cancels = [e for e in _queued() if e["action"] == "cancel" and e["kind"] == "poc"]
    assert len(cancels) == 1 and cancels[0]["id"] == place[0]["id"]
