"""Rencana trading XAU/USD (intraday M15 & scalping M5) dari candle asli.

Alur: candle H4/H1/M15/M5 (Twelve Data) → indikator & struktur dihitung di
Python (EMA20/50/200, Supertrend 10×3, RSI14, ATR14, swing high/low, level
sesi) → Claude menyusun rencana (arah, entry, SL, TP1, TP2, masa berlaku) →
geometri divalidasi di sini → chart (chart-img TradingView / cadangan sendiri)
→ dinilai otomatis di run berikutnya (TP1 / SL / tidak terisi).

Ini alat bantu analisa, bukan sinyal yang terbukti punya edge: riset XAU
M1–M15 sebelumnya tanpa edge, makanya setiap rencana dicatat & dinilai.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone

import anthropic

from .analyst import EFFORT, MODEL, _fmt_ts

UTC = timezone.utc
TF_SEC = {"M5": 300, "M15": 900, "H1": 3600, "H4": 14400}


# ------------------------------------------------------------------ indikator

def ema(vals: list[float], n: int) -> list[float]:
    k = 2 / (n + 1)
    out, e = [], None
    for v in vals:
        e = v if e is None else v * k + e * (1 - k)
        out.append(e)
    return out


def atr(bars: list[list[float]], n: int = 14) -> list[float]:
    out, a, prev = [], None, None
    for t, o, h, l, c in bars:
        tr = h - l if prev is None else max(h - l, abs(h - prev), abs(l - prev))
        a = tr if a is None else (a * (n - 1) + tr) / n
        out.append(a)
        prev = c
    return out


def rsi(closes: list[float], n: int = 14) -> list[float]:
    out, ag, al = [50.0], 0.0, 0.0
    for i in range(1, len(closes)):
        d = closes[i] - closes[i - 1]
        g, lo = max(d, 0), max(-d, 0)
        if i <= n:
            ag += g / n
            al += lo / n
        else:
            ag = (ag * (n - 1) + g) / n
            al = (al * (n - 1) + lo) / n
        out.append(100 - 100 / (1 + ag / al) if al else 100.0)
    return out


def supertrend(bars: list[list[float]], n: int = 10, mult: float = 3.0) -> list[int]:
    """+1 naik / -1 turun per bar."""
    a = atr(bars, n)
    dirs, up_prev, dn_prev, d = [], None, None, 1
    for i, (t, o, h, l, c) in enumerate(bars):
        mid = (h + l) / 2
        up, dn = mid - mult * a[i], mid + mult * a[i]
        if up_prev is not None and bars[i - 1][4] > up_prev:
            up = max(up, up_prev)
        if dn_prev is not None and bars[i - 1][4] < dn_prev:
            dn = min(dn, dn_prev)
        if dn_prev is not None and c > dn_prev:
            d = 1
        elif up_prev is not None and c < up_prev:
            d = -1
        dirs.append(d)
        up_prev, dn_prev = up, dn
    return dirs


def swings(bars: list[list[float]], k: int = 3, limit: int = 4) -> dict:
    """Swing high/low terkonfirmasi (fractal k bar kiri-kanan), terbaru dulu."""
    hi, lo = [], []
    for i in range(k, len(bars) - k):
        h, l = bars[i][2], bars[i][3]
        if all(h >= bars[j][2] for j in range(i - k, i + k + 1)):
            hi.append((bars[i][0], h))
        if all(l <= bars[j][3] for j in range(i - k, i + k + 1)):
            lo.append((bars[i][0], l))
    return {"highs": hi[-limit:][::-1], "lows": lo[-limit:][::-1]}


def tf_summary(name: str, bars: list[list[float]]) -> dict:
    closes = [b[4] for b in bars]
    e20, e50, e200 = ema(closes, 20), ema(closes, 50), ema(closes, 200)
    a = atr(bars)
    st = supertrend(bars)
    r = rsi(closes)
    last = bars[-1]
    slope = lambda s: s[-1] - s[-6] if len(s) > 6 else 0.0
    if closes[-1] > e50[-1] > e200[-1] and slope(e50) > 0:
        trend = "bullish"
    elif closes[-1] < e50[-1] < e200[-1] and slope(e50) < 0:
        trend = "bearish"
    else:
        trend = "sideways"
    return {
        "tf": name, "t": last[0], "close": last[4], "atr": round(a[-1], 2),
        "ema20": round(e20[-1], 2), "ema50": round(e50[-1], 2), "ema200": round(e200[-1], 2),
        "ema50_slope": round(slope(e50), 2), "supertrend": "naik" if st[-1] > 0 else "turun",
        "st_flip_bars_ago": next((i for i in range(1, len(st)) if st[-i - 1] != st[-1]), len(st)),
        "rsi": round(r[-1], 1), "trend_rule": trend, "swings": swings(bars),
        "recent": bars[-24:],
    }


# ------------------------------------------------------------------ Claude

DIR = {"type": "string", "enum": ["bullish", "bearish", "sideways"]}
PLAN = {
    "type": "object",
    "additionalProperties": False,
    "required": ["style", "action", "order", "entry", "sl", "tp1", "tp2", "valid_hours",
                 "invalidation", "reason"],
    "properties": {
        "style": {"type": "string", "enum": ["intraday", "scalping"]},
        "action": {"type": "string", "enum": ["buy", "sell", "no_trade"]},
        "order": {"type": "string", "enum": ["limit", "stop", "market"]},
        "entry": {"type": "number"}, "sl": {"type": "number"},
        "tp1": {"type": "number"}, "tp2": {"type": "number"},
        "valid_hours": {"type": "number"},
        "invalidation": {"type": "string"},
        "reason": {"type": "string"},
    },
}
SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["trend", "plans"],
    "properties": {
        "trend": {
            "type": "object",
            "additionalProperties": False,
            "required": ["h4", "h1", "m15", "m5", "summary"],
            "properties": {"h4": DIR, "h1": DIR, "m15": DIR, "m5": DIR, "summary": {"type": "string"}},
        },
        "plans": {"type": "array", "items": PLAN},
    },
}

SYSTEM = """Kamu trader emas (XAU/USD) yang membuat rencana trading teknikal dari data candle asli
untuk trader ritel Indonesia. Bahasa Indonesia, lugas.

Buat TEPAT dua rencana:
1. style "intraday": arah dari H4/H1, entry & SL berdasarkan struktur M15, target dalam sesi (beberapa jam).
2. style "scalping": arah dari M15/H1, entry & SL berdasarkan struktur M5, target kecil (≤ 1–2 jam).

Aturan:
- Ikuti arah tren timeframe besar. Kalau tren campur/sideways tanpa level jelas, atau ada event
  berdampak tinggi < 30 menit lagi, pilih action "no_trade" (isi angka entry/sl/tp dengan harga
  sekarang, dan jelaskan di reason apa yang ditunggu).
- Entry di level yang masuk akal: pullback ke EMA/swing/level sesi (order "limit"), atau
  breakout swing (order "stop"); "market" hanya kalau harga sedang tepat di zona entry.
- SL di balik swing/struktur terdekat + buffer kecil. Jarak SL kira-kira 0,8–2,5× ATR timeframe
  entry (M15 untuk intraday, M5 untuk scalping).
- TP1 ≥ 1R (target struktur terdekat), TP2 ≈ 2R atau level berikutnya.
- BUY: sl < entry < tp1 ≤ tp2. SELL: tp2 ≤ tp1 < entry < sl.
- valid_hours: berapa jam order boleh menunggu terisi (intraday 2–6, scalping 0,5–2).
- reason 1–2 kalimat (kenapa arah & level itu), invalidation 1 kalimat (kondisi rencana batal).
- Pakai hanya angka yang ada di data; jangan mengarang level jauh dari harga."""


def _fmt_tf(s: dict) -> list[str]:
    sw = s["swings"]
    lines = [
        f"### {s['tf']} — close {s['close']:.2f}, ATR14 {s['atr']:.2f}, RSI14 {s['rsi']}",
        f"EMA20 {s['ema20']:.2f} · EMA50 {s['ema50']:.2f} (slope 5 bar {s['ema50_slope']:+.2f}) · "
        f"EMA200 {s['ema200']:.2f} · Supertrend(10,3) {s['supertrend']} sejak {s['st_flip_bars_ago']} bar · "
        f"aturan tren: {s['trend_rule']}",
        "Swing high: " + ", ".join(f"{p:.2f} ({_fmt_ts(t)})" for t, p in sw["highs"]),
        "Swing low: " + ", ".join(f"{p:.2f} ({_fmt_ts(t)})" for t, p in sw["lows"]),
        "Candle terakhir (WIB, O/H/L/C):",
    ]
    lines += [f"  {_fmt_ts(b[0])[4:]} {b[1]:.2f}/{b[2]:.2f}/{b[3]:.2f}/{b[4]:.2f}" for b in s["recent"][-16:]]
    return lines


def build_prompt(ctx: dict) -> str:
    lines = [f"Waktu sekarang: {_fmt_ts(ctx['now'])}", f"Sesi target: {ctx['target_label']}",
             f"Harga sekarang: {ctx['price']:.2f}", ""]
    lv = ctx["levels"]
    lines.append("Level sesi: " + " · ".join(f"{k} {v:.2f}" for k, v in lv.items() if v))
    b = ctx.get("briefing")
    if b:
        lines += ["", f"Briefing fundamental: bias {b['bias']} ({b['confidence']}) — {b['headline']}"]
        for e in b.get("event_risks", [])[:4]:
            lines.append(f"- Event: {e['time_wib']} {e['event']}")
    for s in ctx["tfs"]:
        lines += [""] + _fmt_tf(s)
    return "\n".join(lines)


def plan(ctx: dict, client: anthropic.Anthropic | None = None) -> tuple[dict, dict]:
    client = client or anthropic.Anthropic()
    prompt = build_prompt(ctx)
    kwargs = dict(model=MODEL, max_tokens=16000, system=SYSTEM,
                  output_config={"effort": EFFORT, "format": {"type": "json_schema", "schema": SCHEMA}},
                  messages=[{"role": "user", "content": prompt}])
    try:
        with client.beta.messages.stream(betas=["server-side-fallback-2026-07-01"],
                                         fallbacks="default", **kwargs) as stream:
            msg = stream.get_final_message()
    except anthropic.BadRequestError:
        with client.messages.stream(**kwargs) as stream:
            msg = stream.get_final_message()
    if msg.stop_reason in ("refusal", "max_tokens"):
        raise RuntimeError(f"rencana trading gagal: {msg.stop_reason}")
    data = json.loads(next(b.text for b in msg.content if b.type == "text"))
    return data, {"input_tokens": msg.usage.input_tokens, "output_tokens": msg.usage.output_tokens}


# ------------------------------------------------------------------ validasi

def validate(p: dict, price: float, atr_entry: float, atr_h1: float) -> dict:
    """Tolak rencana yang geometrinya tidak masuk akal → no_trade + catatan."""
    p = dict(p)
    p["tf"] = "M15" if p["style"] == "intraday" else "M5"
    p["valid_hours"] = max(0.5, min(float(p["valid_hours"]), 8.0))
    if p["action"] == "no_trade":
        return p
    e, sl, t1, t2 = p["entry"], p["sl"], p["tp1"], p["tp2"]
    problems = []
    if p["action"] == "buy" and not (sl < e < t1 <= t2):
        problems.append("urutan level BUY salah")
    if p["action"] == "sell" and not (t2 <= t1 < e < sl):
        problems.append("urutan level SELL salah")
    risk = abs(e - sl)
    if atr_entry and not (0.4 * atr_entry <= risk <= 4.0 * atr_entry):
        problems.append(f"jarak SL {risk:.2f} di luar 0,4–4× ATR {atr_entry:.2f}")
    if risk and abs(t1 - e) / risk < 0.9:
        problems.append("TP1 < 1R")
    if atr_h1 and abs(e - price) > 2.0 * atr_h1:
        problems.append("entry terlalu jauh dari harga")
    if p["order"] == "limit" and ((p["action"] == "buy" and e > price) or (p["action"] == "sell" and e < price)):
        p["order"] = "stop"
    if p["order"] == "stop" and ((p["action"] == "buy" and e < price) or (p["action"] == "sell" and e > price)):
        p["order"] = "limit"
    if problems:
        p["rejected"] = "; ".join(problems)
        p["action_proposed"] = p["action"]
        p["action"] = "no_trade"
        return p
    p["risk"] = round(risk, 2)
    p["rr1"] = round(abs(t1 - e) / risk, 2)
    p["rr2"] = round(abs(t2 - e) / risk, 2)
    return p


# ------------------------------------------------------------------ penilaian

def evaluate(p: dict, created: int, m5: list[list[float]], now: float) -> dict | None:
    """Hasil rencana dari candle M5 setelah dibuat. None = belum bisa dinilai."""
    if p["action"] == "no_trade":
        return None
    expiry = created + p["valid_hours"] * 3600
    bars = [b for b in m5 if b[0] >= created]
    if not bars:
        return None
    buy = p["action"] == "buy"
    e, sl, t1, t2, risk = p["entry"], p["sl"], p["tp1"], p["tp2"], p["risk"]
    filled_at = None
    for i, (t, o, h, l, c) in enumerate(bars):
        if filled_at is None:
            if t >= expiry:
                break
            hit = (p["order"] == "market" or
                   (p["order"] == "limit" and (l <= e if buy else h >= e)) or
                   (p["order"] == "stop" and (h >= e if buy else l <= e)))
            if not hit:
                continue
            filled_at = t
        # setelah terisi: SL dulu kalau di bar yang sama (konservatif)
        if (l <= sl) if buy else (h >= sl):
            return {"result": "sl", "r": -1.0, "filled": filled_at, "closed": t}
        if (h >= t2) if buy else (l <= t2):
            return {"result": "tp2", "r": round(abs(t2 - e) / risk, 2), "filled": filled_at, "closed": t}
        if (h >= t1) if buy else (l <= t1):
            return {"result": "tp1", "r": round(abs(t1 - e) / risk, 2), "filled": filled_at, "closed": t}
        if t >= expiry + 6 * 3600:  # terisi tapi tidak kena apa-apa → tutup paksa
            r = ((c - e) if buy else (e - c)) / risk
            return {"result": "expired", "r": round(r, 2), "filled": filled_at, "closed": t}
    if filled_at is None and now >= expiry and bars[-1][0] >= expiry:
        return {"result": "not_filled", "r": 0.0, "filled": None, "closed": None}
    return None
