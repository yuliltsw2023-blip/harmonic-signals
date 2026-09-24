"""Aturan eksekusi tambahan (24 Sep 2026) — hasil evaluasi dua SL (AUD/CHF POC
H4, GBP/USD Bat D1):

1. split_closed()        Twelve Data mengembalikan candle yang sedang berjalan
                         sebagai baris terakhir; scanner lama menganggapnya
                         "candle terakhir yang sudah close" (reaksi & stage
                         POC dinilai dari candle berumur 1 menit).
2. harmonic_confirmed()  Mode entry "confirmed" harmonic: hanya D yang sudah
                         terkonfirmasi sebagai pivot, entry market, SL di luar
                         D (bukan X) — mengganti pending limit buta di mid PRZ.
3. poc_confirmed()       Mode entry "confirmed" POC: pullback sudah menyentuh
                         area POC + candle close terakhir menunjukkan reaksi,
                         entry market, SL di luar ekstrem pullback.
4. exec_grade_ok() / session_ok()   gate antrean MT5 (grade minimum, jam sesi).

Semua fungsi murni (tanpa network) supaya bisa dipakai scanner & backtest.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from config import settings
from config.pairs import asset_class, price_decimals
from config.patterns import TOLERANCE
from lib.pivots import atr

INTERVAL_SEC = {"15min": 900, "30min": 1800, "1h": 3600, "4h": 14400, "1day": 86400, "1week": 604800}
GRADE_ORDER = {"A": 3, "B": 2, "C": 1}


def parse_dt(s: str) -> datetime:
    s = s.strip()
    fmt = "%Y-%m-%d %H:%M:%S" if " " in s else "%Y-%m-%d"
    return datetime.strptime(s, fmt).replace(tzinfo=timezone.utc)


def split_closed(candles: list[dict], interval: str, now: datetime | None = None) -> tuple[list[dict], dict | None]:
    """(candle yang sudah close, candle berjalan | None). Candle terakhir dianggap
    masih berjalan kalau waktu mulai + panjang interval > sekarang."""
    if not candles:
        return candles, None
    now = now or datetime.now(timezone.utc)
    sec = INTERVAL_SEC.get(interval, 3600)
    last = candles[-1]
    try:
        start = parse_dt(last["datetime"])
    except ValueError:
        return candles, None
    if start + timedelta(seconds=sec) > now:
        return candles[:-1], last
    return candles, None


# ---------------------------------------------------------------------------
# Harmonic — mode confirmed
# ---------------------------------------------------------------------------

def harmonic_confirmed(cand: dict, candles: list[dict]) -> bool:
    """Isi cand["exec"] kalau setup layak dieksekusi market sekarang:
    D sudah pivot terkonfirmasi (completed), rasio & confluence valid, harga
    masih di sisi TP dari D tapi belum lari > CONFIRM_MAX_RUN_AD × AD, dan R:R
    ke TP2 (dari harga sekarang, SL = D ± buffer) ≥ MIN_RR_TP2."""
    if cand.get("d_projected", True) or cand["points"].get("D") is None:
        return False
    if cand["deviation_max"] > TOLERANCE or cand["prz"]["confluence"] < 2:
        return False
    p = cand["points"]
    X, A, D = p["X"]["price"], p["A"]["price"], p["D"]["price"]
    bull = cand["direction"] == "bull"
    px = cand["current_price"]
    ad = abs(A - D)
    if ad <= 0:
        return False
    run = (px - D) if bull else (D - px)
    if run < 0 or run > settings.CONFIRM_MAX_RUN_AD * ad:
        return False
    cls = asset_class(cand["pair"])
    ap = settings.asset_params(cand["pair"], cand.get("timeframe"))
    buf = max(abs(A - X) * ap["sl_buf_xa"], settings.CONFIRM_SL_ATR.get(cls, 0.2) * atr(candles), X * ap["sl_min_pct"])
    # SL di luar D (pivot yang sudah terkonfirmasi). Tepi PRZ sengaja TIDAK
    # dipakai: dengan band 0.5% harga, PRZ bisa melewati X (lihat PRZ_BAND_XA).
    sl = (D - buf) if bull else (D + buf)
    sign = 1 if bull else -1
    tps = {"tp1": D + sign * ad * 0.382, "tp2": D + sign * ad * 0.618, "tp3": D + sign * ad * 1.0}
    risk = abs(px - sl)
    if risk <= 0:
        return False
    rr = {k: (abs(tp - px) / risk if (tp - px) * sign > 0 else 0.0) for k, tp in tps.items()}
    if rr["tp2"] < settings.MIN_RR_TP2_PREGRADE:
        cand["exec_reject"] = f"R:R confirmed ke TP2 {rr['tp2']:.2f} < {settings.MIN_RR_TP2_PREGRADE}"
        return False
    cand["exec"] = {"mode": "confirmed", "order": "market", "entry": px, "sl": sl, "tps": tps, "rr": rr,
                    "run_ad": run / ad, "buffer": buf}
    return True


# ---------------------------------------------------------------------------
# POC — mode confirmed
# ---------------------------------------------------------------------------

def poc_confirmed(cand: dict, candles: list[dict]) -> bool:
    """Isi cand["exec"] kalau: bias jelas, leg cukup panjang, kedalaman POC di
    range, harga di dalam / baru keluar dari VA, pullback sudah menyentuh area
    POC, candle close terakhir bereaksi, dan R:R ke TP2 dari harga sekarang
    (SL di luar ekstrem pullback) ≥ MIN_RR_TP2."""
    if cand.get("bias") is None or cand["stage"] not in ("in_va", "reacted"):
        return False
    if cand["leg"]["bars"] < settings.POC_MIN_LEG_BARS:
        return False
    if settings.POC_MIN_LEG_ATR > 0 and cand.get("leg_atr", 0.0) < settings.POC_MIN_LEG_ATR:
        return False
    if not (settings.POC_DEPTH_MIN <= cand["depth"] <= settings.POC_DEPTH_MAX):
        return False
    if not cand.get("reactions"):
        return False
    bull = cand["direction"] == "bull"
    poc, vah, val = cand["poc"], cand["vah"], cand["val"]
    pb = cand.get("pullback_extreme")
    if pb is None:
        return False
    touch = poc + (vah - poc) * settings.CONFIRM_POC_TOUCH if bull else poc - (poc - val) * settings.CONFIRM_POC_TOUCH
    if (bull and pb > touch) or (not bull and pb < touch):
        cand["exec_reject"] = "pullback belum menyentuh area POC"
        return False
    px = cand["current_price"]
    cls = asset_class(cand["pair"])
    buf = settings.CONFIRM_SL_ATR.get(cls, 0.2) * atr(candles)
    sl = (min(pb, val) - buf) if bull else (max(pb, vah) + buf)
    risk = abs(px - sl)
    if risk <= 0:
        return False
    sign = 1 if bull else -1
    tps = cand["tps"]
    rr = {k: (abs(tp - px) / risk if (tp - px) * sign > 0 else 0.0) for k, tp in tps.items()}
    if rr["tp2"] < settings.MIN_RR_TP2_PREGRADE:
        cand["exec_reject"] = f"R:R confirmed ke TP2 {rr['tp2']:.2f} < {settings.MIN_RR_TP2_PREGRADE}"
        return False
    cand["exec"] = {"mode": "confirmed", "order": "market", "entry": px, "sl": sl, "tps": tps, "rr": rr, "buffer": buf}
    return True


# ---------------------------------------------------------------------------
# Gate antrean MT5
# ---------------------------------------------------------------------------

def exec_grade_ok(grade: str | None) -> bool:
    return GRADE_ORDER.get(str(grade or "C").upper(), 0) >= GRADE_ORDER.get(settings.EXEC_MIN_GRADE, 2)


def session_ok(pair: str, timeframe: str, now: datetime | None = None) -> bool:
    """Filter jam sesi hanya untuk entry market forex/metal di H1/H4."""
    win = settings.EXEC_SESSION_UTC
    if not win or timeframe not in ("M15", "M30", "H1", "H4") or asset_class(pair) not in ("forex", "metal"):
        return True
    h = (now or datetime.now(timezone.utc)).hour
    start, end = win[0], win[1]
    return start <= h < end if start <= end else (h >= start or h < end)


def format_exec_notice(cand: dict, grade: str) -> str:
    """Pesan singkat Telegram saat event entry confirmed masuk antrean."""
    d = price_decimals(cand["pair"])
    f = lambda x: f"{x:.{d}f}"
    ex = cand["exec"]
    side = "BUY" if cand["direction"] == "bull" else "SELL"
    what = f"{cand['pattern']} {cand['timeframe']}" if cand.get("kind") != "poc" else f"POC pullback {cand['timeframe']}"
    return (f"🤖 ENTRY CONFIRMED — {cand['pair']} {side} ({what}) · Grade {grade}\n"
            f"Entry market {f(ex['entry'])} · SL {f(ex['sl'])} · TP1 {f(ex['tps']['tp1'])} · TP2 {f(ex['tps']['tp2'])}\n"
            f"R:R TP1 {ex['rr']['tp1']:.1f} · TP2 {ex['rr']['tp2']:.1f} · scan {cand.get('scan_datetime', '-')}")
