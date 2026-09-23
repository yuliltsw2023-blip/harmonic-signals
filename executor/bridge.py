"""Jembatan ke MetaTrader 5 lewat modul resmi `MetaTrader5` (Windows saja).

Modul MT5 di-import lazy di connect() supaya logika sizing/keputusan bisa
di-test di OS lain dengan modul palsu (tests/test_executor.py).
"""

from __future__ import annotations

import hashlib
import math
from datetime import datetime, timezone

from executor.config import ExecutorConfig


class BridgeError(RuntimeError):
    pass


def tag_of(setup_id: str) -> str:
    """Komentar order MT5 maksimal 31 karakter → pakai hash pendek dari id setup."""
    return "HS" + hashlib.sha1(setup_id.encode()).hexdigest()[:8]


def round_lot(lot: float, step: float, vmin: float, vmax: float) -> float:
    if step <= 0:
        return lot
    lot = math.floor(lot / step + 1e-9) * step
    lot = round(lot, 8)
    if lot < vmin:
        return 0.0
    return min(lot, vmax)


def lot_for_risk(equity: float, risk_pct: float, entry: float, sl: float,
                 tick_size: float, tick_value: float, step: float, vmin: float, vmax: float) -> float:
    """Lot supaya rugi di SL = risk_pct % ekuitas. 0.0 = risiko tidak muat lot minimal."""
    dist = abs(entry - sl)
    if dist <= 0 or tick_size <= 0 or tick_value <= 0:
        return 0.0
    loss_per_lot = dist / tick_size * tick_value
    return round_lot(equity * risk_pct / 100 / loss_per_lot, step, vmin, vmax)


def decide_order_type(side: str, entry: float, ask: float, bid: float) -> str:
    """buy: kalau ask sudah ≤ entry → market (harga sudah di zona), kalau tidak buy limit.
    sell: kalau bid sudah ≥ entry → market, kalau tidak sell limit."""
    if side == "buy":
        return "market" if ask <= entry else "limit"
    return "market" if bid >= entry else "limit"


class MT5Bridge:
    def __init__(self, cfg: ExecutorConfig, mt5_module=None):
        self.cfg = cfg
        self.mt5 = mt5_module
        self._symbols: dict[str, str] = {}

    # ------------------------------------------------------------------ koneksi
    def connect(self) -> dict:
        if self.mt5 is None:
            import MetaTrader5 as mt5  # noqa: N813 — hanya ada di Windows
            self.mt5 = mt5
        kw = {}
        if self.cfg.path:
            kw["path"] = self.cfg.path
        if self.cfg.login:
            kw.update(login=int(self.cfg.login), password=self.cfg.password, server=self.cfg.server)
        if not self.mt5.initialize(**kw):
            raise BridgeError(f"MT5 initialize gagal: {self.mt5.last_error()}")
        acc = self.mt5.account_info()
        if acc is None:
            raise BridgeError(f"account_info kosong: {self.mt5.last_error()}")
        return {"login": acc.login, "server": acc.server, "balance": acc.balance,
                "equity": acc.equity, "currency": acc.currency, "trade_allowed": acc.trade_allowed}

    def shutdown(self) -> None:
        if self.mt5 is not None:
            self.mt5.shutdown()

    # ------------------------------------------------------------------ simbol
    def resolve_symbol(self, pair: str) -> str:
        """'EUR/USD' → 'EURUSD' (atau override MT5_SYMBOL_MAP / suffix). Cache."""
        if pair in self._symbols:
            return self._symbols[pair]
        base = pair.replace("/", "")
        candidates = []
        if pair in self.cfg.symbol_map:
            candidates.append(self.cfg.symbol_map[pair])
        candidates += [base + self.cfg.symbol_suffix, base]
        for name in candidates:
            info = self.mt5.symbol_info(name)
            if info is not None:
                self.mt5.symbol_select(name, True)
                self._symbols[pair] = name
                return name
        found = self.mt5.symbols_get(base + "*") or []
        if found:
            name = sorted(found, key=lambda s: len(s.name))[0].name
            self.mt5.symbol_select(name, True)
            self._symbols[pair] = name
            return name
        raise BridgeError(f"simbol {pair} tidak ada di broker (coba MT5_SYMBOL_MAP)")

    # ------------------------------------------------------------------ order
    def place(self, ev: dict) -> dict:
        """Pasang order sesuai event. Return {tickets:[...], lots, type, reason}."""
        mt5 = self.mt5
        symbol = self.resolve_symbol(ev["symbol"])
        info = mt5.symbol_info(symbol)
        tick = mt5.symbol_info_tick(symbol)
        acc = mt5.account_info()
        side, entry, sl = ev["side"], float(ev["entry"]), float(ev["sl"])
        risk = self.cfg.risk_for_grade(ev.get("grade", "B"))
        lot = lot_for_risk(acc.equity, risk, entry, sl, info.trade_tick_size, info.trade_tick_value,
                           info.volume_step, info.volume_min, info.volume_max)
        if lot <= 0:
            return {"tickets": [], "lots": 0.0, "type": "-", "reason": "SL terlalu jauh untuk lot minimal (risiko > batas)"}

        # stop level broker: SL/TP harus ≥ N point dari harga
        min_dist = info.trade_stops_level * info.point
        if abs(entry - sl) < min_dist or abs(entry - float(ev["tp1"])) < min_dist:
            return {"tickets": [], "lots": 0.0, "type": "-", "reason": f"SL/TP lebih dekat dari stop level broker ({info.trade_stops_level} point)"}

        otype = decide_order_type(side, entry, tick.ask, tick.bid)
        legs = [("TP1", float(ev["tp1"])), ("TP2", float(ev["tp2"]))]
        half = round_lot(lot / 2, info.volume_step, info.volume_min, info.volume_max)
        if self.cfg.split_tp and half > 0:
            plan = [(name, tp, half) for name, tp in legs]
        else:
            plan = [("TP1", float(ev["tp1"]), lot)]

        tag = tag_of(ev["id"])
        tickets = []
        for name, tp, vol in plan:
            price = entry if otype == "limit" else (tick.ask if side == "buy" else tick.bid)
            req = {
                "symbol": symbol,
                "volume": vol,
                "price": float(price),
                "sl": round(sl, info.digits),
                "tp": round(tp, info.digits),
                "magic": self.cfg.magic,
                "comment": f"{tag}|{name}",
                "type_time": mt5.ORDER_TIME_GTC,
            }
            if otype == "limit":
                req.update({"action": mt5.TRADE_ACTION_PENDING,
                            "type": mt5.ORDER_TYPE_BUY_LIMIT if side == "buy" else mt5.ORDER_TYPE_SELL_LIMIT,
                            "type_filling": mt5.ORDER_FILLING_RETURN})
            else:
                req.update({"action": mt5.TRADE_ACTION_DEAL,
                            "type": mt5.ORDER_TYPE_BUY if side == "buy" else mt5.ORDER_TYPE_SELL,
                            "deviation": self.cfg.deviation_points,
                            "type_filling": self._filling(info)})
            res = mt5.order_send(req)
            if res is None or res.retcode not in (mt5.TRADE_RETCODE_DONE, mt5.TRADE_RETCODE_PLACED):
                code = getattr(res, "retcode", None)
                msg = getattr(res, "comment", mt5.last_error())
                # kalau leg pertama gagal, jangan lanjut; kalau leg kedua gagal, laporkan
                return {"tickets": tickets, "lots": lot, "type": otype,
                        "reason": f"order_send {name} gagal: {code} {msg}"}
            tickets.append(int(res.order or getattr(res, "deal", 0)))
        return {"tickets": tickets, "lots": lot, "type": otype, "reason": "ok", "tag": tag, "symbol": symbol}

    def _filling(self, info):
        mt5 = self.mt5
        mode = getattr(info, "filling_mode", 0)
        if mode & getattr(mt5, "SYMBOL_FILLING_IOC", 2):
            return mt5.ORDER_FILLING_IOC
        if mode & getattr(mt5, "SYMBOL_FILLING_FOK", 1):
            return mt5.ORDER_FILLING_FOK
        return mt5.ORDER_FILLING_RETURN

    def cancel(self, setup_id: str) -> int:
        """Hapus semua pending order milik setup ini. Return jumlah yang dihapus."""
        mt5 = self.mt5
        tag = tag_of(setup_id)
        n = 0
        for o in mt5.orders_get() or []:
            if o.magic == self.cfg.magic and str(o.comment).startswith(tag):
                res = mt5.order_send({"action": mt5.TRADE_ACTION_REMOVE, "order": o.ticket})
                if res is not None and res.retcode == mt5.TRADE_RETCODE_DONE:
                    n += 1
        return n

    def active_setups(self) -> set[str]:
        """Tag setup yang masih punya pending order atau posisi terbuka."""
        mt5 = self.mt5
        tags = set()
        for o in (mt5.orders_get() or []) + list(mt5.positions_get() or []):
            if o.magic == self.cfg.magic:
                tags.add(str(o.comment).split("|")[0])
        return tags

    # ------------------------------------------------------------------ manajemen
    def manage_breakeven(self) -> list[str]:
        """Kalau leg TP1 sudah tertutup (profit) dan leg TP2 masih terbuka →
        SL leg TP2 dipindah ke harga entry (skill: TP1 hit → SL ke BE)."""
        mt5 = self.mt5
        positions = [p for p in (mt5.positions_get() or []) if p.magic == self.cfg.magic]
        open_tags = {str(p.comment) for p in positions}
        moved = []
        for p in positions:
            tag, _, leg = str(p.comment).partition("|")
            if leg != "TP2" or f"{tag}|TP1" in open_tags:
                continue
            be = p.price_open
            already = (p.type == mt5.POSITION_TYPE_BUY and p.sl >= be) or (p.type == mt5.POSITION_TYPE_SELL and 0 < p.sl <= be)
            if already:
                continue
            # pastikan TP1 memang tertutup untung (bukan SL kena → TP2 pasti ikut kena juga)
            deals = mt5.history_deals_get(datetime.now(timezone.utc).replace(hour=0, minute=0, second=0) - self._days(7),
                                          datetime.now(timezone.utc)) or []
            tp1_closed_profit = any(d.magic == self.cfg.magic and str(d.comment).startswith(f"{tag}|TP1")
                                    and d.entry == mt5.DEAL_ENTRY_OUT and d.profit > 0 for d in deals)
            if not tp1_closed_profit:
                continue
            res = mt5.order_send({"action": mt5.TRADE_ACTION_SLTP, "position": p.ticket,
                                  "symbol": p.symbol, "sl": be, "tp": p.tp})
            if res is not None and res.retcode == mt5.TRADE_RETCODE_DONE:
                moved.append(f"{p.symbol} {tag} SL→BE {be}")
        return moved

    @staticmethod
    def _days(n: int):
        from datetime import timedelta
        return timedelta(days=n)

    def daily_pnl(self) -> float:
        """Realized P/L hari ini (UTC) dari deal keluar milik eksekutor."""
        mt5 = self.mt5
        start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        total = 0.0
        for d in mt5.history_deals_get(start, datetime.now(timezone.utc)) or []:
            if d.magic == self.cfg.magic and d.entry == mt5.DEAL_ENTRY_OUT:
                total += d.profit + d.commission + d.swap
        return total
