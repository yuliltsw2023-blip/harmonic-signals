from lib.pivots import atr, find_pivots, swing_pivots, zigzag


def test_find_pivots_basic():
    highs = [1, 2, 3, 5, 3, 2, 1, 2, 3, 4, 3, 2, 1]
    lows = [h - 1 for h in highs]
    piv = find_pivots(highs, lows, left=2, right=2)
    types = [(p["idx"], p["type"]) for p in piv]
    assert (3, "H") in types
    assert (6, "L") in types
    assert (9, "H") in types


def test_zigzag_alternates_and_keeps_extreme():
    raw = [
        {"idx": 1, "price": 1.0, "type": "L"},
        {"idx": 3, "price": 1.5, "type": "H"},
        {"idx": 5, "price": 1.7, "type": "H"},  # sejenis, lebih tinggi → replace
        {"idx": 7, "price": 1.2, "type": "L"},
    ]
    zz = zigzag(raw)
    assert [p["idx"] for p in zz] == [1, 5, 7]


def test_zigzag_min_move_filters_noise():
    raw = [
        {"idx": 1, "price": 1.00, "type": "L"},
        {"idx": 3, "price": 1.01, "type": "H"},  # leg 0.01 < min_move → skip
        {"idx": 5, "price": 1.30, "type": "H"},
        {"idx": 7, "price": 1.10, "type": "L"},
    ]
    zz = zigzag(raw, min_move=0.05)
    assert [p["idx"] for p in zz] == [1, 5, 7]


def test_atr_positive_and_swing_pivots_have_datetime():
    from tests.fixtures import synthetic_random_walk
    candles = synthetic_random_walk(120)
    assert atr(candles) > 0
    piv = swing_pivots(candles, 3, 3, 1.0)
    assert piv
    assert all("datetime" in p for p in piv)
    # alternasi
    for a, b in zip(piv, piv[1:]):
        assert a["type"] != b["type"]
