"""Backtest as-of: putar ulang scanner + eksekutor bar per bar di histori
data/history/*.json (unduh: scripts/manual/fetch_history.py).

Meniru live setepat mungkin:
  * scan di menit ke-1 setelah candle buka; Twelve Data mengembalikan candle
    berjalan sebagai baris terakhir → di sini candle berjalan = O=H=L=C=open
    (mode lama) atau dibuang (CLOSED_CANDLE_ONLY);
  * dedup per key/stage (TTL 7 hari) dengan key yang sama seperti lib.state;
  * antrean order idempoten per setup id (EA: TagExists → tidak dipasang ulang);
  * eksekutor: limit di entry (market kalau harga sudah lewat), 50/50 TP1-TP2,
    SL→BE setelah TP1 untung, expiry pending per TF, cancel dari scanner;
  * weekend: scan dilewati seperti cron (Senin–Jumat, Jumat ≥22 UTC skip).
Tidak dimodelkan: batas 3 setup aktif, rugi harian 3%, spread/slippage, dan
Claude (grade = rule grade; Claude hanya bisa MENURUNKAN → jumlah sinyal di sini
= batas atas). Tie-break SL vs TP di bar yang sama = SL (konservatif). Hasil per
trade dalam R (1R = jarak entry→SL posisi penuh).
"""

from __future__ import annotations

import json
import os
from datetime import date, datetime, timedelta, timezone

from config import settings
from config.pairs import asset_class, market_247, pip_size
from lib.pivots import atr
from lib.exec_rules import INTERVAL_SEC, exec_grade_ok, harmonic_confirmed, parse_dt, poc_confirmed, session_ok
from lib.grading import htf_alignment, htf_trend, rule_grade
from lib.mtf import attach_mtf
from lib.orders import harmonic_event, poc_event
from lib.poc import analyze_poc, poc_alignment, rule_grade_poc
from lib.scanner import analyze_candles, is_forex_closed
from lib.state import _hdate, poc_key, signal_key

TF_INTERVAL = {"H1": "1h", "H4": "4h", "D1": "1day"}
TF_HOURS = {"H1": 1, "H4": 4, "D1": 24}
HIST_DIR = os.path.join("data", "history")
DEDUP_TTL = 7 * 86400


def load_history(pair: str, interval: str) -> list[dict]:
    fn = os.path.join(HIST_DIR, f"{pair.replace('/', '')}_{interval}.json")
    if not os.path.exists(fn):
        raise FileNotFoundError(fn)
    return json.load(open(fn))


def weekly_from_daily(daily: list[dict]) -> list[dict]:
    """Agregasi D1 → W1 (minggu ISO, datetime = Senin)."""
    out: list[dict] = []
    cur_key = None
    for d in daily:
        day = date.fromisoformat(d["datetime"][:10])
        y, w, _ = day.isocalendar()
        key = (y, w)
        if key != cur_key:
            monday = day - timedelta(days=day.weekday())
            out.append({"datetime": monday.isoformat(), "open": d["open"], "high": d["high"], "low": d["low"], "close": d["close"]})
            cur_key = key
        else:
            b = out[-1]
            b["high"] = max(b["high"], d["high"])
            b["low"] = min(b["low"], d["low"])
            b["close"] = d["close"]
    return out


class PairBacktest:
    def __init__(self, pair: str, tf: str, bars: list[dict], htf_bars: list[dict],
                 lookback: int = 200, last_n: int | None = None, ltf_bars: list[dict] | None = None):
        self.pair, self.tf = pair, tf
        self.bars = bars
        self.htf_bars = htf_bars
        self.ltf_bars = ltf_bars or []
        self.lep = [parse_dt(b["datetime"]).timestamp() for b in self.ltf_bars]
        self.lsec = INTERVAL_SEC.get(settings.LTF_OF.get(tf) or "1h", 3600)
        self._lj = 0
        self.lookback = lookback
        self.interval = TF_INTERVAL[tf]
        self.htf_interval = settings.HTF_OF[tf]
        self.hsec = INTERVAL_SEC[self.htf_interval]
        self.ep = [parse_dt(b["datetime"]).timestamp() for b in bars]
        self.hep = [parse_dt(b["datetime"]).timestamp() for b in htf_bars]
        self.start = max(lookback, len(bars) - last_n) if last_n else lookback
        self.signaled: dict[str, float] = {}
        self.pending: dict[str, dict] = {}
        self.placed: set[str] = set()
        self.positions: dict[str, dict] = {}
        self.trades: list[dict] = []
        self.stats = {"scans": 0, "signals": 0, "placed": 0, "cancelled": 0, "expired": 0, "market_fills": 0}
        self._hj = 0

    # ----------------------------------------------------------------- helpers
    def _seen(self, key: str, now_ts: float) -> bool:
        exp = self.signaled.get(key)
        return exp is not None and exp > now_ts

    def _mark(self, key: str, now_ts: float) -> None:
        self.signaled[key] = now_ts + DEDUP_TTL

    def _htf_asof(self, now_ts: float, px: float) -> list[dict]:
        while self._hj < len(self.htf_bars) and self.hep[self._hj] + self.hsec <= now_ts:
            self._hj += 1
        closed = self.htf_bars[max(0, self._hj - settings.HTF_OUTPUTSIZE):self._hj]
        # candle HTF berjalan ikut (close = harga sekarang), seperti data live
        return closed + [{"datetime": "", "open": px, "high": px, "low": px, "close": px}]

    def _ltf_asof(self, now_ts: float) -> list[dict]:
        while self._lj < len(self.ltf_bars) and self.lep[self._lj] + self.lsec <= now_ts:
            self._lj += 1
        return self.ltf_bars[max(0, self._lj - 200):self._lj]

    def _hgrade(self, cand: dict, htf: list[dict]) -> str:
        trend = htf_trend(htf) if len(htf) >= 30 else "neutral"
        cand["htf_timeframe"] = self.htf_interval
        cand["htf_trend"] = trend
        cand["htf_alignment"] = htf_alignment(cand, trend)
        return rule_grade(cand)["grade"]

    def _pgrade(self, poc: dict, htf: list[dict]) -> str:
        trend = htf_trend(htf) if len(htf) >= 30 else "neutral"
        poc["htf_timeframe"] = self.htf_interval
        poc["htf_trend"] = trend
        poc["htf_alignment"] = poc_alignment(poc, trend)
        return rule_grade_poc(poc)["grade"]

    def _hkey(self, cand: dict, stage: str) -> str:
        return signal_key(cand["pair"], cand["timeframe"], cand["pattern"], _hdate(cand), stage)

    def _pkey(self, poc: dict, stage: str) -> str:
        return poc_key(poc["pair"], poc["timeframe"], poc["leg_date"], stage)

    # ----------------------------------------------------------------- scan
    def _scan(self, i: int, now_ts: float, now: datetime) -> list[tuple[str, dict, dict]]:
        bar = self.bars[i]
        if settings.CLOSED_CANDLE_ONLY:
            window = self.bars[i - self.lookback:i]
        else:
            forming = {"datetime": bar["datetime"], "open": bar["open"], "high": bar["open"], "low": bar["open"], "close": bar["open"]}
            window = self.bars[i - self.lookback + 1:i] + [forming]
        htf = self._htf_asof(now_ts, bar["open"])
        ltf = self._ltf_asof(now_ts) if self.ltf_bars else []
        events: list[tuple[str, dict, dict]] = []
        self.stats["scans"] += 1

        def mtf_meta(c: dict) -> dict:
            # selalu dihitung (untuk analisis post-hoc); faktor grade hanya kalau MTF_CONFLICT_FILTER
            m = attach_mtf(c, window, ltf, self.tf)
            return {"ltf_bias": m["ltf_bias"], "own_trend": m["own_trend"], "conflict_ltf": m["conflict_ltf"],
                    "conflict_own": m["conflict_own"]}

        for cand in analyze_candles(self.pair, self.tf, window):
            stage = cand.get("stage")
            meta = {"kind": "harmonic", "pattern": cand["pattern"], "direction": cand["direction"], "stage": stage,
                    **mtf_meta(cand)}
            if (settings.HARMONIC_EXEC_MODE == "confirmed" and not cand["d_projected"] and stage in ("in_prz", "left")):
                ck = self._hkey(cand, "confirmed")
                if not self._seen(ck, now_ts) and harmonic_confirmed(cand, window):
                    g = self._hgrade(cand, htf)
                    if g != "C" and exec_grade_ok(g) and session_ok(self.pair, self.tf, now):
                        events.append(("place", harmonic_event(cand, {"grade": g}), {**meta, "grade": g, "htf": cand["htf_alignment"]}))
                    self._mark(ck, now_ts)
            if cand["pre_grade"] == "FAIL":
                if stage == "pierced" and any(self._seen(self._hkey(cand, s), now_ts) for s in ("approaching", "in_prz")):
                    ck = self._hkey(cand, "cancel")
                    if not self._seen(ck, now_ts):
                        events.append(("cancel", harmonic_event(cand, action="cancel"), meta))
                        self._mark(ck, now_ts)
                continue
            if stage not in settings.SIGNAL_STAGES:
                continue
            mk = self._hkey(cand, stage)
            if self._seen(mk, now_ts):
                continue
            if stage == "left":
                if not any(self._seen(self._hkey(cand, s), now_ts) for s in ("approaching", "in_prz")):
                    continue
                self._mark(mk, now_ts)
                events.append(("cancel", harmonic_event(cand, action="cancel"), meta))
                continue
            g = self._hgrade(cand, htf)
            if g == "C":
                continue
            self._mark(mk, now_ts)
            self.stats["signals"] += 1
            if settings.HARMONIC_EXEC_MODE == "limit" and exec_grade_ok(g):
                events.append(("place", harmonic_event(cand, {"grade": g}), {**meta, "grade": g, "htf": cand["htf_alignment"]}))

        if settings.POC_ENABLED and self.tf in settings.POC_TIMEFRAMES:
            poc = analyze_poc(self.pair, self.tf, window)
            if poc is not None:
                meta = {"kind": "poc", "pattern": "POC", "direction": poc["direction"], "stage": poc["stage"],
                        **mtf_meta(poc)}
                if poc["stage"] in settings.POC_CANCEL_ON_STAGE and any(
                        self._seen(self._pkey(poc, s), now_ts) for s in ("approaching", "in_va", "reacted")):
                    ck = self._pkey(poc, "cancel")
                    if not self._seen(ck, now_ts):
                        events.append(("cancel", poc_event(poc, action="cancel"), meta))
                        self._mark(ck, now_ts)
                if settings.POC_EXEC_MODE == "confirmed":
                    ck = self._pkey(poc, "confirmed")
                    if not self._seen(ck, now_ts) and poc_confirmed(poc, window):
                        g = self._pgrade(poc, htf)
                        if g != "C" and exec_grade_ok(g) and session_ok(self.pair, self.tf, now):
                            events.append(("place", poc_event(poc), {**meta, "grade": g, "htf": poc["htf_alignment"]}))
                        self._mark(ck, now_ts)
                if poc["pre_grade"] == "PASS":
                    mk = self._pkey(poc, poc["stage"])
                    if not self._seen(mk, now_ts):
                        g = self._pgrade(poc, htf)
                        if g != "C":
                            self._mark(mk, now_ts)
                            self.stats["signals"] += 1
                            if settings.POC_EXEC_MODE == "limit" and exec_grade_ok(g):
                                events.append(("place", poc_event(poc), {**meta, "grade": g, "htf": poc["htf_alignment"]}))
        return events

    # ----------------------------------------------------------------- orders
    def _apply(self, events, i: int, now_ts: float, bar: dict) -> None:
        for kind, ev, meta in events:
            sid = ev["id"]
            if kind == "cancel":
                if self.pending.pop(sid, None) is not None:
                    self.stats["cancelled"] += 1
                continue
            if sid in self.placed:
                continue
            self.placed.add(sid)
            buy = ev["side"] == "buy"
            px = bar["open"]
            market = ev.get("order") == "market" or (buy and px <= ev["entry"]) or ((not buy) and px >= ev["entry"])
            sl = ev["sl"]
            if settings.BT_SL_WIDEN_ATR > 0:
                a = atr(self.bars[max(0, i - 30):i])
                sl = sl - settings.BT_SL_WIDEN_ATR * a if buy else sl + settings.BT_SL_WIDEN_ATR * a
            self.pending[sid] = {
                **ev, **meta, "sl": sl, "buy": buy, "market": market, "placed_i": i, "placed_ts": now_ts,
                "expires_ts": now_ts + ev.get("expires_hours", 24) * 3600,
            }
            self.stats["placed"] += 1

    def _execute(self, i: int, now_ts: float, bar: dict) -> None:
        o_, h_, l_ = bar["open"], bar["high"], bar["low"]
        # pending → fill / expiry
        for sid, o in list(self.pending.items()):
            fill = None
            if o["market"]:
                fill = o_
            elif o["buy"] and l_ <= o["entry"]:
                fill = min(o["entry"], o_)
            elif (not o["buy"]) and h_ >= o["entry"]:
                fill = max(o["entry"], o_)
            if fill is not None:
                risk = abs(fill - o["sl"])
                if risk <= 0:
                    del self.pending[sid]
                    continue
                if o["market"]:
                    self.stats["market_fills"] += 1
                sign = 1 if o["buy"] else -1
                far = float("inf") * sign
                trail = settings.BT_TRAIL and o["kind"] in settings.BT_TRAIL_KINDS
                if trail and settings.BT_TRAIL_KEEP_TP1:
                    legs = {"tp1": {"sl": o["sl"], "tp": o["tp1"], "open": True, "w": 0.5},
                            "trail": {"sl": o["sl"], "tp": far, "open": True, "w": 0.5}}
                elif trail:
                    legs = {"trail": {"sl": o["sl"], "tp": far, "open": True, "w": 1.0}}
                elif settings.BT_EXIT_R > 0:
                    sign = 1 if o["buy"] else -1
                    legs = {"tpR": {"sl": o["sl"], "tp": fill + sign * settings.BT_EXIT_R * risk, "open": True, "w": 1.0}}
                else:
                    legs = {"tp1": {"sl": o["sl"], "tp": o["tp1"], "open": True, "w": 0.5},
                            "tp2": {"sl": o["sl"], "tp": o["tp2"], "open": True, "w": 0.5}}
                self.positions[sid] = {
                    **o, "fill": fill, "fill_i": i, "fill_ts": now_ts, "risk": risk, "r": 0.0, "legs": legs,
                    "best": fill, "trail_on": False,
                }
                del self.pending[sid]
            elif now_ts >= o["expires_ts"]:
                del self.pending[sid]
                self.stats["expired"] += 1
        # posisi → SL / TP (konservatif: SL dulu kalau dua-duanya kena)
        for sid, p in list(self.positions.items()):
            buy = p["buy"]
            if "trail" in p["legs"] and p["legs"]["trail"]["open"] and i > p["fill_i"]:
                self._trail(p, i)
            for name, leg in p["legs"].items():
                if not leg["open"]:
                    continue
                sl, tp = leg["sl"], leg["tp"]
                hit_sl = l_ <= sl if buy else h_ >= sl
                hit_tp = h_ >= tp if buy else l_ <= tp
                # Bar pengisian limit: urutan intrabar tidak diketahui (high bisa terjadi
                # sebelum harga turun ke limit) → TP tidak dihitung di bar itu, hanya SL.
                if i == p["fill_i"] and not p["market"]:
                    hit_tp = False
                w = leg.get("w", 0.5)
                if hit_sl:
                    exit_px = min(o_, sl) if buy else max(o_, sl)
                    p["r"] += w * ((exit_px - p["fill"]) if buy else (p["fill"] - exit_px)) / p["risk"]
                    leg["open"] = False
                    leg["exit"] = "sl" if abs(sl - p["sl"]) > 1e-12 or True else "sl"
                    leg["exit_kind"] = "be" if abs(sl - p["fill"]) < 1e-12 else ("trail" if abs(sl - p["sl"]) > 1e-12 else "sl")
                elif hit_tp:
                    exit_px = max(o_, tp) if buy else min(o_, tp)
                    p["r"] += w * abs(exit_px - p["fill"]) / p["risk"]
                    leg["open"] = False
                    leg["exit_kind"] = name
                    if name == "tp1" and "tp2" in p["legs"] and p["legs"]["tp2"]["open"]:
                        p["legs"]["tp2"]["sl"] = p["fill"]  # SL → BE
            p["best"] = max(p["best"], h_) if buy else min(p["best"], l_)
            if not any(lg["open"] for lg in p["legs"].values()):
                fill_dt = datetime.fromtimestamp(p["fill_ts"], timezone.utc)
                spread = settings.BT_SPREAD.get(asset_class(self.pair), 0.0001)
                if asset_class(self.pair) == "forex":
                    spread = pip_size(self.pair)          # 1 pip
                cost_r = (spread * (p["fill"] if asset_class(self.pair) != "forex" else 1.0)) / p["risk"] if p["risk"] > 0 else 0.0
                self.trades.append({
                    "id": sid, "pair": self.pair, "tf": self.tf, "kind": p["kind"], "pattern": p["pattern"],
                    "direction": p["direction"], "grade": p.get("grade"), "stage": p.get("stage"),
                    "htf": p.get("htf"), "exec_mode": p.get("exec_mode", "limit"), "order": "market" if p["market"] else "limit",
                    "ltf_bias": p.get("ltf_bias"), "own_trend": p.get("own_trend"),
                    "conflict_ltf": p.get("conflict_ltf"), "conflict_own": p.get("conflict_own"),
                    "entry": p["fill"], "sl": p["sl"], "tp1": p["tp1"], "tp2": p["tp2"],
                    "rr1": abs(p["tp1"] - p["fill"]) / p["risk"], "rr2": abs(p["tp2"] - p["fill"]) / p["risk"],
                    "placed": datetime.fromtimestamp(p["placed_ts"], timezone.utc).isoformat(timespec="minutes"),
                    "fill": fill_dt.isoformat(timespec="minutes"), "fill_hour": fill_dt.hour,
                    "exit": datetime.fromtimestamp(now_ts, timezone.utc).isoformat(timespec="minutes"),
                    "exit_ts": now_ts, "bars_held": i - p["fill_i"],
                    "legs": {k: v.get("exit_kind") for k, v in p["legs"].items()},
                    "r": round(p["r"], 4), "cost_r": round(cost_r, 4), "r_net": round(p["r"] - cost_r, 4),
                    "result": "win" if p["r"] > 1e-9 else ("loss" if p["r"] < -1e-9 else "flat"),
                })
                del self.positions[sid]

    def _trail(self, p: dict, i: int) -> None:
        """Geser SL leg trailing memakai info candle yang SUDAH tutup (bar < i):
        aktif setelah profit terbaik ≥ BT_TRAIL_START_R × risiko (SL → BE), lalu ke swing
        terkonfirmasi terakhir. SL hanya bergerak searah profit."""
        leg, buy, n = p["legs"]["trail"], p["buy"], settings.BT_TRAIL_PIVOT
        if not p["trail_on"]:
            gain = (p["best"] - p["fill"]) if buy else (p["fill"] - p["best"])
            if gain < settings.BT_TRAIL_START_R * p["risk"]:
                return
            p["trail_on"] = True
            leg["sl"] = max(leg["sl"], p["fill"]) if buy else min(leg["sl"], p["fill"])
        last = i - 1                                   # candle tutup terakhir
        buf = settings.BT_TRAIL_BUF_ATR * atr(self.bars[max(0, last - 30):last + 1]) if settings.BT_TRAIL_BUF_ATR else 0.0
        close = self.bars[last]["close"]
        for k in range(last - n, max(n - 1, last - 150), -1):
            if buy:
                lk = self.bars[k]["low"]
                if all(lk < self.bars[j]["low"] for j in range(k - n, k)) and all(lk <= self.bars[j]["low"] for j in range(k + 1, k + n + 1)):
                    cand = lk - buf
                    if leg["sl"] < cand < close:
                        leg["sl"] = cand
                    return
            else:
                hk = self.bars[k]["high"]
                if all(hk > self.bars[j]["high"] for j in range(k - n, k)) and all(hk >= self.bars[j]["high"] for j in range(k + 1, k + n + 1)):
                    cand = hk + buf
                    if close < cand < leg["sl"]:
                        leg["sl"] = cand
                    return

    # ----------------------------------------------------------------- run
    def run(self) -> dict:
        skip_weekend = not market_247(self.pair)
        for i in range(self.start, len(self.bars)):
            bar = self.bars[i]
            now_ts = self.ep[i] + 60
            now = datetime.fromtimestamp(now_ts, timezone.utc)
            events = []
            if not (skip_weekend and is_forex_closed(now)):
                events = self._scan(i, now_ts, now)
            self._apply(events, i, now_ts, bar)
            self._execute(i, now_ts, bar)
        return {"pair": self.pair, "tf": self.tf, "trades": self.trades, "stats": self.stats,
                "open_positions": len(self.positions), "pending_left": len(self.pending),
                "from": self.bars[self.start]["datetime"], "to": self.bars[-1]["datetime"]}


# --------------------------------------------------------------------------- ringkasan
def summarize(trades: list[dict]) -> dict:
    n = len(trades)
    if n == 0:
        return {"n": 0}
    wins = [t["r"] for t in trades if t["r"] > 0]
    losses = [t["r"] for t in trades if t["r"] < 0]
    ordered = sorted(trades, key=lambda t: t["exit_ts"])
    eq = peak = dd = 0.0
    for t in ordered:
        eq += t["r"]
        peak = max(peak, eq)
        dd = max(dd, peak - eq)
    net = [t.get("r_net", t["r"]) for t in trades]
    return {
        "n": n, "win%": round(100 * len(wins) / n, 1), "avgR": round(sum(t["r"] for t in trades) / n, 3),
        "sumR": round(sum(t["r"] for t in trades), 1),
        "PF": round(sum(wins) / abs(sum(losses)), 2) if losses else float("inf"),
        "maxDD_R": round(dd, 1),
        "netR": round(sum(net), 1), "netPF": round(sum(x for x in net if x > 0) / abs(sum(x for x in net if x < 0)), 2)
        if any(x < 0 for x in net) else float("inf"),
    }


def group_summary(trades: list[dict], key) -> dict:
    groups: dict[str, list[dict]] = {}
    for t in trades:
        groups.setdefault(str(key(t)), []).append(t)
    return {k: summarize(v) for k, v in sorted(groups.items())}
