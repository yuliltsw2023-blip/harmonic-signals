"""Tahap sinyal harmonic (approaching / in_prz / left), R:R minimum 2,
dukungan timeframe scalping M15/M30, dan job hourly gabungan."""

from config import settings
from config.pairs import SCALP_SYMBOLS, symbols_for
from lib import scanner, state
from lib.grading import pre_grade
from lib.scanner import analyze_candles
from lib.telegram import format_compact, format_left_notice, format_poc_compact
from tests.fixtures import synthetic_bat


def _bat():
    cands = analyze_candles("EUR/USD", "H4", synthetic_bat(bull=True, projected=True))
    return next(c for c in cands if c["pattern"] == "Bat")


def _move(c, price):
    """Pindahkan harga sekarang & hitung ulang jarak ke PRZ (bull)."""
    c["current_price"] = price
    prz = c["prz"]
    if prz["low"] <= price <= prz["high"]:
        c["prz_distance_pct"] = 0.0
    elif price > prz["high"]:
        c["prz_distance_pct"] = (price - prz["high"]) / price
    else:
        c["prz_distance_pct"] = -(prz["low"] - price) / price
    return c


def test_defaults():
    assert settings.SIGNAL_STAGES == ("approaching", "in_prz", "left")
    assert settings.MIN_RR_TP2_PREGRADE == 2.0


def test_in_prz_stage_caption_masuk_zona():
    c = _bat()
    c["scan_datetime"] = "07:41 UTC"
    assert c["stage"] == "in_prz" and c["in_prz"] is True
    assert c["pre_grade"] == "PASS", c["pre_grade_reason"]
    cap = format_compact(c, {"grade": "A"})
    assert "MASUK ZONA" in cap and "scan 07:41 UTC" in cap and "limit" in cap.lower()


def test_approaching_stage_caption_siapkan_order():
    c = _move(_bat(), _bat()["prz"]["high"] * 1.0025)   # 0.25% di atas zona
    assert pre_grade(c) == "PASS", c["pre_grade_reason"]
    assert c["stage"] == "approaching" and c["in_prz"] is False
    cap = format_compact(c, {"grade": "B"})
    assert "SIAPKAN ORDER" in cap and "Limit BUY" in cap and "jangan entry market" in cap


def test_far_and_pierced_fail():
    c = _move(_bat(), _bat()["prz"]["high"] * 1.01)     # 1% di atas zona
    assert pre_grade(c) == "FAIL" and c["stage"] == "far"
    assert "belum actionable" in c["pre_grade_reason"]
    c = _move(_bat(), _bat()["prz"]["low"] * 0.99)      # menembus zona 1% ke arah X
    assert pre_grade(c) == "FAIL" and c["stage"] == "pierced"


def test_completed_d_price_gone_is_left_stage():
    cands = analyze_candles("GBP/USD", "H4", synthetic_bat(bull=False, projected=False))
    c = next(c for c in cands if c["pattern"] == "Bat" and not c["d_projected"])
    assert c["stage"] == "in_prz"                        # fixture: harga masih di zona
    c["current_price"] = c["prz"]["low"] * 0.99          # bear: harga sudah turun 1% menuju TP
    c["prz_distance_pct"] = (c["prz"]["low"] - c["current_price"]) / c["current_price"]
    assert pre_grade(c) == "PASS" and c["stage"] == "left"
    txt = format_left_notice(c)
    assert "JANGAN KEJAR" in txt and "Kalau limit lo sudah kena" in txt


def test_left_notice_only_after_earlier_stage(monkeypatch):
    state._redis = None
    state._memory.clear()
    monkeypatch.delenv("UPSTASH_REDIS_REST_URL", raising=False)
    c = _bat()
    c["stage"] = "left"
    assert state.earlier_stage_signaled(c) is False
    c["stage"] = "approaching"
    state.mark_signaled(c)
    c["stage"] = "left"
    assert state.earlier_stage_signaled(c) is True
    assert state.is_already_signaled(c) is False          # tahap left sendiri belum dikirim


def test_dedup_key_includes_stage():
    assert state.signal_key("EUR/USD", "H4", "Deep Crab", "20260917", "approaching") == \
        "signal:EUR_USD:H4:DeepCrab:20260917:approaching"


def test_stage_off_is_not_sent(monkeypatch, capsys):
    from tests.test_scanner_dry_run import FakeTD, _setup
    _setup(monkeypatch)
    monkeypatch.setattr(settings, "SIGNAL_STAGES", ("approaching",))
    assert scanner.run_scan("H4", pairs=["EUR/USD"], dry_run=True) == 0
    out = capsys.readouterr().out
    assert "[stage-off] EUR/USD Bat bull" in out and "Would send" not in out


def test_rr_below_2_fails():
    c = _bat()
    c["rr"]["tp2"] = 1.8
    assert pre_grade(c) == "FAIL"
    assert "R:R ke TP2 1.80 < 2.0" in c["pre_grade_reason"]


def test_poc_caption_has_limit_line():
    cand = {"pair": "GBP/AUD", "timeframe": "H1", "direction": "bear", "stage": "approaching",
            "stage_label": "MENDEKATI Value Area", "val": 1.88356, "vah": 1.88957, "poc": 1.88737,
            "sl": 1.89067, "tps": {"tp1": 1.88102, "tp2": 1.87851}, "rr": {"tp1": 1.9, "tp2": 2.7},
            "current_price": 1.88200, "current_datetime": "2026-09-17 07:00:00", "scan_datetime": "07:41 UTC",
            "grade": {"grade": "B"}}
    cap = format_poc_compact(cand)
    assert "Limit SELL <b>1.88737</b> (POC)" in cap and "harga sekarang 1.88200" in cap and "scan 07:41 UTC" in cap


def test_tf_scale_shrinks_bands_for_scalping():
    base = settings.asset_params("EUR/USD")
    m15 = settings.asset_params("EUR/USD", "M15")
    assert m15["prz_band"] == base["prz_band"] * 0.3
    assert m15["entry_tol"] == base["entry_tol"] * 0.3
    assert m15["sl_buf_xa"] == base["sl_buf_xa"]
    assert settings.asset_params("EUR/USD", "H4") == base


def test_m15_universe_intervals_and_htf():
    assert symbols_for("M15") == SCALP_SYMBOLS and len(SCALP_SYMBOLS) == 4
    assert scanner.INTERVAL_OF["M15"] == "15min" and scanner.INTERVAL_OF["M30"] == "30min"
    assert settings.HTF_OF["M15"] == "1h" and settings.HTF_OF["M30"] == "4h"
    from lib.chart_img import INTERVAL_OF as CI
    assert CI["M15"] == "15m" and CI["M30"] == "30m"


def test_hourly_job_picks_due_timeframes():
    import importlib.util, os, pathlib, sys
    scripts = pathlib.Path(__file__).resolve().parents[1] / "scripts"
    sys.path.insert(0, str(scripts))
    env_before = dict(os.environ)  # _bootstrap memuat .env asli → jangan bocor ke test lain
    try:
        spec = importlib.util.spec_from_file_location("scan_hourly", scripts / "scan_hourly.py")
        mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    finally:
        os.environ.clear(); os.environ.update(env_before)
    assert mod.due_timeframes(0) == ["H1", "H4", "D1"]
    assert mod.due_timeframes(4) == ["H1", "H4"]
    assert mod.due_timeframes(7) == ["H1"]
