#!/usr/bin/env python3
"""Loop eksekutor MT5.

    python -m executor.run --once     # tes koneksi + proses antrean sekali
    python -m executor.run            # jalan terus (Ctrl+C untuk berhenti)

Berhenti darurat tanpa matiin program: buat file executor/STOP, atau set key
Upstash `mt5:halt` = 1 (bisa dari HP lewat console Upstash). Pending order
yang sudah terpasang TIDAK dibatalkan otomatis saat halt — batalkan manual
di MT5 kalau perlu."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import traceback
from datetime import datetime, timezone

from executor.config import ExecutorConfig, ROOT

if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from executor.bridge import BridgeError, MT5Bridge  # noqa: E402
from lib import state  # noqa: E402
from lib.orders import is_expired  # noqa: E402


def _utf8():
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def log(msg: str) -> None:
    print(f"[{datetime.now(timezone.utc).strftime('%H:%M:%S')}] {msg}", flush=True)


class Executor:
    def __init__(self, cfg: ExecutorConfig, bridge: MT5Bridge | None = None):
        self.cfg = cfg
        self.bridge = bridge or MT5Bridge(cfg)
        self.state = self._load_state()
        self.halted_today: str | None = None   # tanggal UTC saat batas rugi harian kena

    # ------------------------------------------------------------------ state lokal
    def _load_state(self) -> dict:
        try:
            with open(self.cfg.state_file, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return {"orders": {}, "done": []}

    def _save_state(self) -> None:
        os.makedirs(os.path.dirname(self.cfg.state_file), exist_ok=True)
        with open(self.cfg.state_file, "w", encoding="utf-8") as f:
            json.dump(self.state, f, indent=1, ensure_ascii=False)

    # ------------------------------------------------------------------ notifikasi
    def notify(self, text: str) -> None:
        log(text)
        if not self.cfg.telegram or not os.environ.get("TELEGRAM_BOT_TOKEN", "").strip():
            return
        try:
            from lib.telegram import send_message
            send_message(f"🤖 <b>MT5</b> · {text}")
        except Exception as e:  # noqa: BLE001
            log(f"telegram gagal: {e}")

    # ------------------------------------------------------------------ halt
    def halted(self) -> str | None:
        if os.path.exists(self.cfg.stop_file):
            return "file STOP ada"
        if state.halt_flag():
            return "key Upstash mt5:halt aktif"
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if self.halted_today == today:
            return "batas rugi harian tercapai"
        return None

    def check_daily_loss(self) -> None:
        try:
            pnl = self.bridge.daily_pnl()
            acc = self.bridge.mt5.account_info()
            limit = -acc.balance * self.cfg.daily_loss_pct / 100
            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            if pnl <= limit and self.halted_today != today:
                self.halted_today = today
                self.notify(f"⛔ Rugi hari ini {pnl:.2f} {acc.currency} ≥ {self.cfg.daily_loss_pct}% saldo → "
                            f"tidak pasang order baru sampai besok (UTC)")
        except Exception as e:  # noqa: BLE001
            log(f"cek rugi harian gagal: {e}")

    # ------------------------------------------------------------------ event
    def handle(self, ev: dict) -> None:
        sid, action = ev["id"], ev["action"]
        rec = self.state["orders"].get(sid)
        if action == "cancel":
            n = self.bridge.cancel(sid)
            if rec:
                rec["cancelled_at"] = ev["created_at"]
            self._save_state()
            if n:
                self.notify(f"❌ {ev.get('label', sid)}: {n} pending dibatalkan ({ev.get('stage')})")
            return
        if action != "place":
            return
        if is_expired(ev):
            log(f"skip {sid}: event kedaluwarsa ({ev['created_at']})")
            return
        if rec and rec.get("tickets"):
            log(f"skip {sid}: sudah terpasang (tiket {rec['tickets']})")
            return
        reason = self.halted()
        if reason:
            log(f"skip {sid}: halt ({reason})")
            return
        active = self.bridge.active_setups()
        if len(active) >= self.cfg.max_open:
            log(f"skip {sid}: setup aktif {len(active)} ≥ MAX_OPEN_SETUPS {self.cfg.max_open}")
            return
        res = self.bridge.place(ev)
        self.state["orders"][sid] = {
            "tickets": res["tickets"], "lots": res["lots"], "type": res["type"],
            "symbol": res.get("symbol"), "tag": res.get("tag"), "placed_at": ev["created_at"],
            "expires_hours": ev.get("expires_hours", 24), "label": ev.get("label"), "reason": res["reason"],
        }
        self._save_state()
        if res["tickets"]:
            side = "BUY" if ev["side"] == "buy" else "SELL"
            self.notify(f"✅ {ev.get('label', sid)} · {res['type']} {side} {res['lots']} lot @ {ev['entry']} · "
                        f"SL {ev['sl']} · TP1 {ev['tp1']} · TP2 {ev['tp2']} · Grade {ev.get('grade', '?')} · tiket {res['tickets']}")
        else:
            self.notify(f"⚠️ {ev.get('label', sid)} tidak dipasang: {res['reason']}")

    def expire_pendings(self) -> None:
        now = datetime.now(timezone.utc)
        for sid, rec in list(self.state["orders"].items()):
            if not rec.get("tickets") or rec.get("cancelled_at") or rec.get("expired_at"):
                continue
            placed = datetime.fromisoformat(rec["placed_at"])
            if placed.tzinfo is None:
                placed = placed.replace(tzinfo=timezone.utc)
            if (now - placed).total_seconds() > rec.get("expires_hours", 24) * 3600:
                n = self.bridge.cancel(sid)
                rec["expired_at"] = now.isoformat(timespec="seconds")
                self._save_state()
                if n:
                    self.notify(f"⌛ {rec.get('label', sid)}: {n} pending kedaluwarsa dibatalkan")

    # ------------------------------------------------------------------ loop
    def tick(self) -> int:
        n = 0
        for ev in state.pop_order_events(50):
            try:
                self.handle(ev)
                n += 1
            except BridgeError as e:
                self.notify(f"⚠️ {ev.get('label', ev.get('id'))}: {e}")
            except Exception:  # noqa: BLE001
                log(f"event {ev.get('id')} error:\n{traceback.format_exc()}")
        for msg in self.bridge.manage_breakeven():
            self.notify(f"🔒 {msg}")
        self.expire_pendings()
        self.check_daily_loss()
        return n

    def run(self, once: bool = False) -> int:
        info = self.bridge.connect()
        log(f"MT5 terhubung: akun {info['login']} @ {info['server']} · saldo {info['balance']} {info['currency']} · "
            f"ekuitas {info['equity']} · algo trading {'ON' if info['trade_allowed'] else 'OFF (nyalakan tombol Algo Trading di MT5!)'}")
        for pair in ("EUR/USD", "GBP/USD", "USD/JPY", "XAU/USD", "BTC/USD"):
            try:
                log(f"  simbol {pair} → {self.bridge.resolve_symbol(pair)}")
            except BridgeError as e:
                log(f"  simbol {pair}: {e}")
        log(f"risiko/trade {self.cfg.risk_pct}% (Grade B ×{self.cfg.risk_pct_b_factor}) · max setup {self.cfg.max_open} · "
            f"batas rugi harian {self.cfg.daily_loss_pct}% · antrean {state.backend_name()}")
        if not info["trade_allowed"]:
            self.notify("⚠️ Algo Trading di terminal MT5 masih OFF — order tidak akan masuk sampai dinyalakan")
        self.notify(f"eksekutor jalan (akun {info['login']}, ekuitas {info['equity']} {info['currency']})")
        try:
            while True:
                n = self.tick()
                if once:
                    log(f"selesai --once ({n} event diproses)")
                    return 0
                time.sleep(self.cfg.poll_sec)
        except KeyboardInterrupt:
            log("berhenti (Ctrl+C)")
            return 0
        finally:
            self.bridge.shutdown()


def main() -> int:
    _utf8()
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true", help="proses antrean sekali lalu keluar")
    ap.add_argument("--check", action="store_true", help="hanya tes koneksi + mapping simbol, tidak sentuh antrean")
    args = ap.parse_args()
    cfg = ExecutorConfig.from_env()
    if not cfg.login:
        log("MT5_LOGIN kosong → pakai akun yang sedang login di terminal MT5 (harus sudah terbuka)")
    ex = Executor(cfg)
    if args.check:
        info = ex.bridge.connect()
        log(f"MT5 terhubung: akun {info['login']} @ {info['server']} · saldo {info['balance']} {info['currency']} · "
            f"ekuitas {info['equity']} · tombol Algo Trading {'ON' if info['algo_button'] else 'OFF (klik tombol Algo Trading di toolbar MT5!)'}")
        for pair in ("EUR/USD", "GBP/USD", "USD/JPY", "XAU/USD", "BTC/USD", "ETH/USD"):
            try:
                sym = ex.bridge.resolve_symbol(pair)
                tick = ex.bridge.mt5.symbol_info_tick(sym)
                if tick is None or not tick.bid:
                    time.sleep(1.5)  # baru masuk Market Watch → tunggu tick pertama
                    tick = ex.bridge.mt5.symbol_info_tick(sym)
                log(f"  {pair} → {sym}  bid {getattr(tick, 'bid', None)} ask {getattr(tick, 'ask', None)}")
            except BridgeError as e:
                log(f"  {pair}: {e}")
        log(f"antrean: {state.backend_name()} · halt: {state.halt_flag()}")
        ex.bridge.shutdown()
        return 0
    return ex.run(once=args.once)


if __name__ == "__main__":
    sys.exit(main())
