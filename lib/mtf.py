"""Filter konflik antar-timeframe (24 Sep 2026).

Kasus GBP/USD 23 Sep: harmonic Bat D1 BUY dikirim saat H4 & H1 berstruktur
LH/LL dan screener H1 sistem ini sendiri mengirim SELL. Skill menyebut ini
"overlapping pattern conflict" → skip. Di sini dibuat mekanis:

  * LTF structure  : bias swing (HH+HL / LH+LL, pivot 5/5) di TF satu tingkat
                     di bawah TF sinyal (D1→4h, H4→1h; H1 tidak ada). Bias yang
                     berlawanan dengan arah sinyal = konflik.
  * Own-TF trend   : posisi close vs EMA20/EMA50 di TF sinyal sendiri (opsional,
                     settings.MTF_OWN_TREND) — ketat, karena pattern reversal
                     hampir selalu terbentuk melawan trend jangka pendek.

attach_mtf() mengisi cand["mtf"]; rule_grade / rule_grade_poc menurunkan
faktor "mtf" ke C kalau settings.MTF_CONFLICT_FILTER aktif dan konflik.
"""

from __future__ import annotations

from config import settings
from lib.grading import htf_trend
from lib.pivots import swing_pivots
from lib.poc import _structure


def ltf_bias(candles: list[dict], pivot_n: int = 5) -> str | None:
    """'bull' / 'bear' / None dari 2 swing high + 2 swing low terakhir."""
    if not candles or len(candles) < 40:
        return None
    pivots = swing_pivots(candles, pivot_n, pivot_n, settings.MIN_LEG_ATR)
    st = _structure(pivots)
    return st["bias"] if st else None


def attach_mtf(cand: dict, own_candles: list[dict], ltf_candles: list[dict] | None, timeframe: str) -> dict:
    want = cand["direction"]                      # "bull" / "bear"
    lb = ltf_bias(ltf_candles) if ltf_candles else None
    own = htf_trend(own_candles) if own_candles else "neutral"
    own_dir = "bull" if own == "up" else "bear" if own == "down" else None
    conflict_ltf = lb is not None and lb != want
    conflict_own = own_dir is not None and own_dir != want
    conflict = conflict_ltf or (settings.MTF_OWN_TREND and conflict_own)
    reason = []
    if conflict_ltf:
        reason.append(f"struktur {settings.LTF_OF.get(timeframe) or 'LTF'} {lb.upper()} melawan sinyal")
    if settings.MTF_OWN_TREND and conflict_own:
        reason.append(f"trend {timeframe} {own} melawan sinyal")
    cand["mtf"] = {
        "ltf_tf": settings.LTF_OF.get(timeframe), "ltf_bias": lb, "own_trend": own,
        "conflict_ltf": conflict_ltf, "conflict_own": conflict_own, "conflict": conflict,
        "reason": "; ".join(reason) if reason else "tidak ada konflik",
    }
    return cand["mtf"]


def mtf_factor(cand: dict) -> str | None:
    """Faktor grade 'mtf' (A/C) kalau filter aktif dan data ada; None = tidak dipakai."""
    m = cand.get("mtf")
    if not settings.MTF_CONFLICT_FILTER or m is None:
        return None
    return "C" if m["conflict"] else "A"
