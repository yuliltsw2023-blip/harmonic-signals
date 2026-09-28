import pytest

from config import settings
from lib.harmonics import extract_xabcd, match_pattern


@pytest.fixture
def combo(monkeypatch):
    monkeypatch.setattr(settings, "HARMONIC_COMBO_SEARCH", True)


def _piv(seq):
    return [{"idx": i * 5, "price": p, "type": t, "datetime": f"2026-01-{i + 1:02d}"} for i, (t, p) in enumerate(seq)]


def _candles(pivs, last_close):
    n = pivs[-1]["idx"] + 4
    out = [{"high": 0, "low": 0, "close": 0, "datetime": "x"} for _ in range(n)]
    for i in range(n):
        out[i] = {"high": last_close + 1, "low": last_close - 1, "close": last_close, "datetime": "x"}
    for p in pivs:
        out[p["idx"]] = {"high": p["price"], "low": p["price"], "close": p["price"], "datetime": p["datetime"]}
    return out


# Gartley bull dengan dua swing kecil di dalam leg AB (X tidak termasuk 4 pivot terakhir)
SEQ = [("L", 100.0), ("H", 200.0), ("L", 150.0), ("H", 175.0), ("L", 138.2), ("H", 165.0)]


def test_old_method_misses_nonconsecutive_structure(monkeypatch):
    monkeypatch.setattr(settings, "HARMONIC_COMBO_SEARCH", False)
    piv = _piv(SEQ)
    assert not [m for m in match_pattern(extract_xabcd(piv, _candles(piv, 160))) if m["pattern"] == "Gartley"]


def test_combo_finds_gartley(combo):
    piv = _piv(SEQ)
    ms = match_pattern(extract_xabcd(piv, _candles(piv, 160)))
    g = [m for m in ms if m["pattern"] == "Gartley"]
    assert g and g[0]["structure"]["X"]["price"] == 100.0 and g[0]["structure"]["B"]["price"] == 138.2
    assert abs(g[0]["d_ideal"] - 121.4) < 1e-6


def test_combo_c_second_last_when_cd_leg_running(combo):
    piv = _piv(SEQ + [("L", 150.0)])          # pivot kecil di tengah leg CD, belum menembus C
    ms = match_pattern(extract_xabcd(piv, _candles(piv, 140)))
    assert any(m["pattern"] == "Gartley" and m["structure"]["C"]["price"] == 165.0 for m in ms)


def test_combo_drops_structure_when_price_breaks_c(combo):
    piv = _piv(SEQ)
    c = _candles(piv, 160)
    c[-1]["high"] = 170.0                      # candle setelah C menembus C
    assert not [m for m in match_pattern(extract_xabcd(piv, c)) if m["structure"]["C"]["price"] == 165.0]
