"""ENTRY_MODE=in_prz (sinyal hanya saat harga sudah di PRZ), R:R minimum 2,
dan dukungan timeframe scalping M15/M30."""

from config import settings
from config.pairs import SCALP_SYMBOLS, symbols_for
from lib import scanner
from lib.grading import pre_grade
from lib.scanner import analyze_candles
from lib.telegram import format_compact
from tests.fixtures import synthetic_bat


def _bat():
    cands = analyze_candles("EUR/USD", "H4", synthetic_bat(bull=True, projected=True))
    return next(c for c in cands if c["pattern"] == "Bat")


def test_default_mode_is_in_prz_and_min_rr_2():
    assert settings.ENTRY_MODE == "in_prz"
    assert settings.MIN_RR_TP2_PREGRADE == 2.0


def test_price_inside_prz_passes_and_is_flagged():
    c = _bat()
    assert c["prz_distance_pct"] <= settings.asset_params("EUR/USD")["entry_tol"]
    assert c["in_prz"] is True
    assert c["pre_grade"] == "PASS", c["pre_grade_reason"]
    cap = format_compact(c, {"grade": "A"})
    assert "di PRZ ✅ entry sekarang" in cap


def test_price_still_far_from_prz_fails_in_in_prz_mode(monkeypatch):
    c = _bat()
    # harga 0.25% di atas PRZ: dulu (mode approach, 0.35%) lolos, sekarang ditolak
    c["current_price"] = c["prz"]["high"] * 1.0025
    c["prz_distance_pct"] = (c["current_price"] - c["prz"]["high"]) / c["current_price"]
    assert pre_grade(c) == "FAIL"
    assert "belum masuk PRZ" in c["pre_grade_reason"]
    assert c["in_prz"] is False
    assert "dari PRZ" in format_compact(c, {"grade": "B"})

    monkeypatch.setattr(settings, "ENTRY_MODE", "approach")
    assert pre_grade(c) == "PASS", c["pre_grade_reason"]


def test_completed_d_also_requires_price_in_prz():
    cands = analyze_candles("GBP/USD", "H4", synthetic_bat(bull=False, projected=False))
    c = next(c for c in cands if c["pattern"] == "Bat" and not c["d_projected"])
    assert c["pre_grade"] == "PASS", c["pre_grade_reason"]  # fixture: harga masih di zona
    # harga sudah lari 1% dari PRZ (bear: turun) → entry sudah lewat, harus ditolak
    c["current_price"] = c["prz"]["low"] * 0.99
    c["prz_distance_pct"] = (c["prz"]["low"] - c["current_price"]) / c["current_price"]
    assert pre_grade(c) == "FAIL" and "belum masuk PRZ" in c["pre_grade_reason"]


def test_rr_below_2_fails():
    c = _bat()
    c["rr"]["tp2"] = 1.8
    assert pre_grade(c) == "FAIL"
    assert "R:R ke TP2 1.80 < 2.0" in c["pre_grade_reason"]


def test_tf_scale_shrinks_bands_for_scalping():
    base = settings.asset_params("EUR/USD")
    m15 = settings.asset_params("EUR/USD", "M15")
    assert m15["prz_band"] == base["prz_band"] * 0.3
    assert m15["entry_tol"] == base["entry_tol"] * 0.3
    assert m15["sl_buf_xa"] == base["sl_buf_xa"]  # buffer SL tidak di-scale
    assert settings.asset_params("EUR/USD", "H4") == base


def test_m15_universe_intervals_and_htf():
    assert symbols_for("M15") == SCALP_SYMBOLS and len(SCALP_SYMBOLS) == 4
    assert symbols_for("M30") == SCALP_SYMBOLS
    assert scanner.INTERVAL_OF["M15"] == "15min" and scanner.INTERVAL_OF["M30"] == "30min"
    assert settings.HTF_OF["M15"] == "1h" and settings.HTF_OF["M30"] == "4h"
    from lib.chart_img import INTERVAL_OF as CI
    assert CI["M15"] == "15m" and CI["M30"] == "30m"
