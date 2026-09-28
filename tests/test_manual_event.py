import pytest

from lib.orders import manual_event


def test_manual_event_tp_mode():
    ev = manual_event("XAU/USD", "buy", 4120, 4111, 4160, 4200, "M15", "GartleyD1")
    assert ev["id"].startswith("m:XAU/USD:M15:GartleyD1:")
    assert ev["kind"] == "manual" and ev["order"] == "limit" and ev["grade"] == "A"
    assert ev["expires_hours"] == 2 and ev["tp2"] == 4200


def test_manual_event_trail_is_harmonic():
    ev = manual_event("XAU/USD", "sell", 4250, 4260, 4200, None, "H1", "RetestShort",
                      order="market", exit_mode="trail", expires_hours=6)
    assert ev["id"].startswith("h:") and ev["kind"] == "harmonic"
    assert ev["tp2"] == 4200 and ev["exec_mode"] == "confirmed" and ev["expires_hours"] == 6


def test_manual_event_rejects_wrong_order():
    with pytest.raises(ValueError):
        manual_event("XAU/USD", "buy", 4120, 4130, 4160, None, "M15", "x")


def test_manual_event_tpbe_carries_risk_and_be():
    ev = manual_event("XAU/USD", "buy", 4120, 4108, 4144, None, "M15", "GartleyD1",
                      exit_mode="tpbe", risk_pct=1.5, be_r=1.0)
    assert ev["id"].startswith("m:") and ev["kind"] == "manual"
    assert ev["risk_pct"] == 1.5 and ev["be_r"] == 1.0


def test_manual_event_plain_tp_has_no_be():
    ev = manual_event("XAU/USD", "buy", 4120, 4108, 4144, None, "M15", "x")
    assert "be_r" not in ev and "risk_pct" not in ev
