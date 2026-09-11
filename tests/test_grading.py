from lib.grading import htf_alignment, htf_trend, rule_grade
from lib.scanner import analyze_candles
from tests.fixtures import synthetic_bat


def _bat():
    return [c for c in analyze_candles("EUR/USD", "H4", synthetic_bat()) if c["pattern"] == "Bat"][0]


def test_htf_trend_up_down_neutral():
    up = [{"close": 1 + i * 0.01} for i in range(60)]
    down = [{"close": 2 - i * 0.01} for i in range(60)]
    assert htf_trend(up) == "up"
    assert htf_trend(down) == "down"
    assert htf_trend(up[:10]) == "neutral"


def test_alignment():
    c = _bat()
    assert htf_alignment(c, "up") == "aligned"
    assert htf_alignment(c, "down") == "counter"
    assert htf_alignment(c, "neutral") == "neutral"


def test_rule_grade_weakest_link():
    c = _bat()
    c["htf_alignment"] = "aligned"
    g = rule_grade(c)
    assert g["grade"] in ("A", "B", "C")
    assert g["grade"] == min(g["factors"].values(), key=lambda x: {"A": 3, "B": 2, "C": 1}[x])

    c["htf_alignment"] = "counter"
    assert rule_grade(c)["grade"] == "C"


def test_rr_scales_with_sl_distance():
    c = _bat()
    assert c["rr"]["tp3"] > c["rr"]["tp2"] > c["rr"]["tp1"] > 0
