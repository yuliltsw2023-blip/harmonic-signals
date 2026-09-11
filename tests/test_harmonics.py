from config.patterns import PATTERNS
from lib.harmonics import ratio_deviation
from lib.scanner import analyze_candles
from tests.fixtures import synthetic_bat, synthetic_gartley, synthetic_random_walk


def test_ratio_deviation_range_and_fixed():
    assert ratio_deviation(0.45, (0.382, 0.5)) == 0.0
    assert abs(ratio_deviation(0.525, (0.382, 0.5)) - 0.05) < 1e-9
    assert abs(ratio_deviation(0.6, 0.618) - (0.018 / 0.618)) < 1e-9


def test_detects_bull_bat_projected():
    cands = analyze_candles("EUR/USD", "H4", synthetic_bat(bull=True, projected=True))
    bats = [c for c in cands if c["pattern"] == "Bat"]
    assert bats, f"Bat tidak terdeteksi, kandidat: {[c['pattern'] for c in cands]}"
    c = bats[0]
    assert c["direction"] == "bull"
    assert c["d_projected"] is True
    assert c["deviation_max"] <= 0.05
    X, A = c["points"]["X"]["price"], c["points"]["A"]["price"]
    assert abs(c["d_ideal"] - (A + (X - A) * 0.886)) < 1e-9
    assert c["prz"]["confluence"] >= 2
    assert c["sl"] < c["points"]["X"]["price"]
    assert c["tps"]["tp1"] < c["tps"]["tp2"] < c["tps"]["tp3"]
    assert c["pre_grade"] == "PASS", c["pre_grade_reason"]


def test_detects_bear_bat_completed():
    cands = analyze_candles("GBP/USD", "H4", synthetic_bat(bull=False, projected=False))
    bats = [c for c in cands if c["pattern"] == "Bat" and not c["d_projected"]]
    assert bats
    c = bats[0]
    assert c["direction"] == "bear"
    assert c["points"]["D"] is not None
    assert c["sl"] > c["points"]["X"]["price"]
    assert c["tps"]["tp1"] > c["tps"]["tp2"] > c["tps"]["tp3"]


def test_detects_gartley():
    cands = analyze_candles("EUR/USD", "H4", synthetic_gartley())
    names = {c["pattern"] for c in cands}
    assert "Gartley" in names


def test_random_walk_rarely_matches_and_never_crashes():
    for seed in range(5):
        cands = analyze_candles("USD/JPY", "H4", synthetic_random_walk(200, base=150.0, seed=seed))
        for c in cands:
            assert c["pattern"] in PATTERNS
            assert c["pre_grade"] in ("PASS", "FAIL")


def test_d_date_uses_c_for_projected():
    c = analyze_candles("EUR/USD", "H4", synthetic_bat())[0]
    assert c["d_date"] == c["points"]["C"]["datetime"][:10].replace("-", "")
