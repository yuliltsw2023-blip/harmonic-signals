"""Eksekutor MT5 dengan modul MetaTrader5 PALSU: sizing lot, limit vs market,
dua leg TP, cancel, breakeven, antrean order, dan event dari scanner."""

from types import SimpleNamespace as NS

import pytest

from executor.bridge import MT5Bridge, decide_order_type, lot_for_risk, tag_of
from executor.config import ExecutorConfig
from lib import state
from lib.orders import harmonic_event, is_expired, poc_event, setup_id
from lib.scanner import analyze_candles
from tests.fixtures import synthetic_bat


class FakeMT5:
    TRADE_ACTION_DEAL, TRADE_ACTION_PENDING, TRADE_ACTION_SLTP, TRADE_ACTION_REMOVE = 1, 5, 6, 8
    ORDER_TYPE_BUY, ORDER_TYPE_SELL, ORDER_TYPE_BUY_LIMIT, ORDER_TYPE_SELL_LIMIT = 0, 1, 2, 3
    ORDER_TIME_GTC = 0
    ORDER_FILLING_FOK, ORDER_FILLING_IOC, ORDER_FILLING_RETURN = 0, 1, 2
    SYMBOL_FILLING_FOK, SYMBOL_FILLING_IOC = 1, 2
    TRADE_RETCODE_DONE, TRADE_RETCODE_PLACED = 10009, 10008
    POSITION_TYPE_BUY, POSITION_TYPE_SELL = 0, 1
    DEAL_ENTRY_IN, DEAL_ENTRY_OUT = 0, 1

    def __init__(self, ask=1.1050, bid=1.1048, equity=10_000.0):
        self.ask, self.bid, self.equity = ask, bid, equity
        self.requests = []
        self.orders = []
        self.positions = []
        self.deals = []
        self._ticket = 100

    def initialize(self, **kw): return True
    def last_error(self): return (0, "ok")
    def shutdown(self): pass
    def account_info(self):
        return NS(login=1, server="Demo", balance=self.equity, equity=self.equity, currency="USD", trade_allowed=True)
    def symbol_info(self, name):
        if name not in ("EURUSD", "XAUUSD"):
            return None
        return NS(name=name, point=0.00001, digits=5, trade_tick_size=0.00001, trade_tick_value=1.0,
                  volume_min=0.01, volume_max=100.0, volume_step=0.01, trade_stops_level=0, filling_mode=2)
    def symbol_info_tick(self, name): return NS(ask=self.ask, bid=self.bid)
    def symbol_select(self, name, on): return True
    def symbols_get(self, pattern=""): return []
    def order_send(self, req):
        self.requests.append(req)
        self._ticket += 1
        if req.get("action") == self.TRADE_ACTION_REMOVE:
            self.orders = [o for o in self.orders if o.ticket != req["order"]]
            return NS(retcode=self.TRADE_RETCODE_DONE, order=req["order"], comment="ok")
        if req.get("action") == self.TRADE_ACTION_PENDING:
            self.orders.append(NS(ticket=self._ticket, magic=req["magic"], comment=req["comment"]))
        return NS(retcode=self.TRADE_RETCODE_DONE, order=self._ticket, deal=self._ticket, comment="ok")
    def orders_get(self): return list(self.orders)
    def positions_get(self): return list(self.positions)
    def history_deals_get(self, a, b): return list(self.deals)


def _cfg(**kw):
    return ExecutorConfig(login="", state_file="/dev/null", **kw)


def test_lot_for_risk_eurusd():
    # ekuitas 10.000, risiko 1% = 100 USD; SL 50 pip = 500 tick × 1 USD/tick/lot = 500 USD/lot → 0.2 lot
    assert lot_for_risk(10_000, 1.0, 1.1000, 1.0950, 0.00001, 1.0, 0.01, 0.01, 100) == pytest.approx(0.2)
    # SL 2000 pip → 0.005 lot < minimal → 0 (jangan dipaksa)
    assert lot_for_risk(10_000, 1.0, 1.1000, 0.9000, 0.00001, 1.0, 0.01, 0.01, 100) == 0.0
    # dibulatkan KE BAWAH ke step
    assert lot_for_risk(10_000, 1.0, 1.1000, 1.0970, 0.00001, 1.0, 0.01, 0.01, 100) == pytest.approx(0.33)


def test_decide_order_type():
    assert decide_order_type("buy", 1.1000, ask=1.1050, bid=1.1048) == "limit"
    assert decide_order_type("buy", 1.1000, ask=1.0990, bid=1.0988) == "market"
    assert decide_order_type("sell", 1.1000, ask=1.0952, bid=1.0950) == "limit"
    assert decide_order_type("sell", 1.1000, ask=1.1012, bid=1.1010) == "market"


def _event(side="buy", entry=1.1000, sl=1.0950, tp1=1.1050, tp2=1.1100, grade="A"):
    return {"id": "h:EUR/USD:H4:Bat:20260917", "action": "place", "kind": "harmonic", "symbol": "EUR/USD",
            "timeframe": "H4", "side": side, "stage": "approaching", "created_at": "2026-09-17T08:00:00+00:00",
            "expires_hours": 36, "label": "EUR/USD Bat BULL H4", "entry": entry, "sl": sl, "tp1": tp1, "tp2": tp2,
            "grade": grade}


def test_place_two_pending_legs_with_risk_split():
    fake = FakeMT5(ask=1.1050, bid=1.1048)
    b = MT5Bridge(_cfg(risk_pct=1.0), mt5_module=fake)
    res = b.place(_event())
    assert res["reason"] == "ok" and res["type"] == "limit" and res["lots"] == pytest.approx(0.2)
    assert len(res["tickets"]) == 2 and len(fake.requests) == 2
    r1, r2 = fake.requests
    assert r1["action"] == fake.TRADE_ACTION_PENDING and r1["type"] == fake.ORDER_TYPE_BUY_LIMIT
    assert r1["volume"] == pytest.approx(0.1) and r2["volume"] == pytest.approx(0.1)
    assert r1["price"] == 1.1 and r1["sl"] == 1.095 and r1["tp"] == 1.105 and r2["tp"] == 1.11
    tag = tag_of("h:EUR/USD:H4:Bat:20260917")
    assert r1["comment"] == f"{tag}|TP1" and r2["comment"] == f"{tag}|TP2" and len(r1["comment"]) <= 31
    assert b.active_setups() == {tag}


def test_grade_b_halves_risk_and_market_when_price_already_in_zone():
    fake = FakeMT5(ask=1.0990, bid=1.0988)
    b = MT5Bridge(_cfg(risk_pct=1.0, risk_pct_b_factor=0.5), mt5_module=fake)
    res = b.place(_event(grade="B"))
    assert res["type"] == "market" and res["lots"] == pytest.approx(0.1)
    assert fake.requests[0]["action"] == fake.TRADE_ACTION_DEAL and fake.requests[0]["type"] == fake.ORDER_TYPE_BUY
    assert fake.requests[0]["price"] == 1.0990 and fake.requests[0]["type_filling"] == fake.ORDER_FILLING_IOC


def test_cancel_removes_only_this_setup():
    fake = FakeMT5()
    b = MT5Bridge(_cfg(), mt5_module=fake)
    b.place(_event())
    other = dict(_event(), id="h:EUR/USD:H4:Gartley:20260910")
    b.place(other)
    assert len(fake.orders) == 4
    assert b.cancel("h:EUR/USD:H4:Bat:20260917") == 2
    assert len(fake.orders) == 2 and all(o.comment.startswith(tag_of(other["id"])) for o in fake.orders)


def test_breakeven_after_tp1_closed_in_profit():
    fake = FakeMT5()
    b = MT5Bridge(_cfg(), mt5_module=fake)
    tag = tag_of("x")
    fake.positions = [NS(ticket=7, magic=260917, comment=f"{tag}|TP2", symbol="EURUSD", type=0,
                         price_open=1.1, sl=1.095, tp=1.11)]
    assert b.manage_breakeven() == []                      # TP1 belum tercatat untung → jangan geser
    fake.deals = [NS(magic=260917, comment=f"{tag}|TP1", entry=1, profit=50.0, commission=0, swap=0)]
    moved = b.manage_breakeven()
    assert moved == ["EURUSD " + tag + " SL→BE 1.1"]
    req = fake.requests[-1]
    assert req["action"] == fake.TRADE_ACTION_SLTP and req["sl"] == 1.1 and req["position"] == 7


def test_symbol_resolution_and_unknown():
    fake = FakeMT5()
    b = MT5Bridge(_cfg(symbol_map={"XAU/USD": "XAUUSD"}), mt5_module=fake)
    assert b.resolve_symbol("EUR/USD") == "EURUSD" and b.resolve_symbol("XAU/USD") == "XAUUSD"
    with pytest.raises(Exception):
        b.resolve_symbol("BBCA.JK")


def test_queue_roundtrip_memory(monkeypatch):
    monkeypatch.delenv("UPSTASH_REDIS_REST_URL", raising=False)
    state._redis = None
    state._memory.clear()
    state._queue.clear()
    state.push_order_event({"id": "a", "action": "place"})
    state.push_order_event({"id": "b", "action": "cancel"})
    assert [e["id"] for e in state.pop_order_events(10)] == ["a", "b"]
    assert state.pop_order_events(10) == []
    assert state.halt_flag() is False


def test_events_from_scanner_candidates():
    c = next(c for c in analyze_candles("EUR/USD", "H4", synthetic_bat()) if c["pattern"] == "Bat")
    ev = harmonic_event(c, {"grade": "A"})
    assert ev["id"] == setup_id(c) == "h:EUR/USD:H4:Bat:" + c["d_date"]
    assert ev["side"] == "buy" and ev["sl"] < ev["entry"] < ev["tp1"] < ev["tp2"] and ev["expires_hours"] == 36
    assert not is_expired(ev)
    old = dict(ev, created_at="2026-01-01T00:00:00+00:00")
    assert is_expired(old)
    cancel = harmonic_event(c, action="cancel")
    assert cancel["action"] == "cancel" and "entry" not in cancel
    pev = poc_event({"kind": "poc", "pair": "GBP/AUD", "timeframe": "H1", "direction": "bear", "stage": "approaching",
                     "leg_date": "20260916", "poc": 1.88737, "sl": 1.89067, "val": 1.88356, "vah": 1.88957,
                     "tps": {"tp1": 1.88102, "tp2": 1.87851}, "grade": {"grade": "B"}})
    assert pev["id"] == "p:GBP/AUD:H1:20260916" and pev["side"] == "sell" and pev["entry"] == 1.88737


def test_decide_order_type_honours_market_flag_and_slip_guard():
    from executor.bridge import decide_order_type, slipped_too_far
    # limit lama: buy market hanya kalau ask sudah <= entry
    assert decide_order_type("buy", 1.1000, ask=1.1005, bid=1.1003) == "limit"
    assert decide_order_type("buy", 1.1000, ask=1.0995, bid=1.0993) == "market"
    # event confirmed: selalu market
    assert decide_order_type("buy", 1.1000, ask=1.1005, bid=1.1003, order="market") == "market"
    assert decide_order_type("sell", 1.1000, ask=1.0995, bid=1.0993, order="market") == "market"
    # guard: harga lari > 25% jarak SL → skip; ke arah menguntungkan tidak dihitung
    assert slipped_too_far("buy", 1.1000, 1.0960, px=1.1011)          # 11 pip > 25% × 40 pip
    assert not slipped_too_far("buy", 1.1000, 1.0960, px=1.1009)
    assert not slipped_too_far("buy", 1.1000, 1.0960, px=1.0990)      # lebih murah → boleh
    assert slipped_too_far("sell", 1.1000, 1.1040, px=1.0989)
