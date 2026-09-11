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


def test_sl_beyond_prz_for_extension_patterns():
    """Butterfly bull: D beyond X → SL harus di bawah PRZ low, dan entry > SL."""
    from tests.fixtures import synthetic_bat
    # Butterfly: B=0.786 XA, D=1.27 XA (beyond X)
    candles = synthetic_bat(bull=True, projected=True, ab_xa=0.786, bc_ab=0.5, ad_xa=1.27)
    cands = [c for c in analyze_candles("EUR/USD", "H4", candles) if c["pattern"] == "Butterfly"]
    assert cands, "Butterfly tidak terdeteksi"
    c = cands[0]
    assert c["sl"] < c["prz"]["low"] < c["entry"]
    assert c["sl"] < c["points"]["X"]["price"]
    assert c["tps"]["tp1"] > c["entry"] > c["sl"]


def test_sl_relative_to_entry_all_candidates():
    """Semua kandidat: bull → SL < entry < TP1; bear → SL > entry > TP1."""
    from tests.fixtures import synthetic_bat, synthetic_random_walk
    sets = [synthetic_bat(bull=True), synthetic_bat(bull=False, projected=False),
            synthetic_bat(bull=True, ab_xa=0.786, bc_ab=0.5, ad_xa=1.27)]
    sets += [synthetic_random_walk(200, seed=s) for s in range(8)]
    for candles in sets:
        for c in analyze_candles("EUR/USD", "H4", candles):
            if c["direction"] == "bull":
                assert c["sl"] < c["entry"] < c["tps"]["tp1"], (c["pattern"], c["sl"], c["entry"])
            else:
                assert c["sl"] > c["entry"] > c["tps"]["tp1"], (c["pattern"], c["sl"], c["entry"])


def test_asset_class_params_and_symbols():
    from config.pairs import asset_class, price_decimals, round_step, market_247, tv_exchange, SCAN_SYMBOLS
    from config import settings
    assert {"XAU/USD", "BTC/USD", "ETH/USD"} <= set(SCAN_SYMBOLS) and "XAG/USD" not in SCAN_SYMBOLS and len(SCAN_SYMBOLS) == 31
    assert asset_class("BTC/USD") == "crypto" and asset_class("XAU/USD") == "metal" and asset_class("EUR/USD") == "forex"
    assert price_decimals("BTC/USD") == 1 and price_decimals("XAU/USD") == 2 and price_decimals("USD/JPY") == 3
    assert round_step("BTC/USD") == 1000 and round_step("XAU/USD") == 50 and round_step("EUR/USD") == 0.01
    assert market_247("BTC/USD") and not market_247("XAU/USD") and not market_247("EUR/USD")
    assert tv_exchange("BTC/USD") == "BITSTAMP" and tv_exchange("XAU/USD") == "OANDA"
    assert asset_class("ETH/USD") == "crypto" and price_decimals("ETH/USD") == 2 and round_step("ETH/USD") == 100
    assert asset_class("XAG/USD") == "metal" and price_decimals("XAG/USD") == 3 and round_step("XAG/USD") == 1.0
    assert market_247("ETH/USD") and not market_247("XAG/USD")
    assert settings.asset_params("BTC/USD")["sl_min_pct"] == 0.015


def test_btc_sl_buffer_at_least_1_5_pct():
    from tests.fixtures import synthetic_bat
    candles = synthetic_bat(bull=True, projected=True, base=1.1)
    for c in candles:  # skala ke harga BTC
        for k in ("open", "high", "low", "close"):
            c[k] = c[k] * 70000
    cands = [c for c in analyze_candles("BTC/USD", "H4", candles) if c["pattern"] == "Bat"]
    assert cands, "Bat tidak terdeteksi di BTC sintetis"
    c = cands[0]
    X = c["points"]["X"]["price"]
    assert c["asset_class"] == "crypto"
    assert X - c["sl"] >= X * 0.015 - 1e-6
