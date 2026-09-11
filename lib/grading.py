"""Deterministic layer: SL, TP, R:R, pre-grade filter, rule-based grade.

Claude (lib/claude_grader.py) menerima hasil ini sebagai konteks dan
memberi grade final + reasoning. Kalau Claude gagal, rule grade dipakai.
"""

from __future__ import annotations

from config import settings
from config.patterns import ACCURATE_DEVIATION, PATTERNS, TOLERANCE

GRADE_ORDER = {"A": 3, "B": 2, "C": 1}


def _worst(*grades: str) -> str:
    return min(grades, key=lambda g: GRADE_ORDER[g])


def entry_price(cand: dict) -> float:
    """Entry referensi = mid PRZ (scaled entry rata-rata)."""
    return cand["prz"]["mid"]


def calculate_sl(cand: dict) -> float:
    """SL beyond X (Carney). Untuk pattern dengan D beyond X (Butterfly, Crab,
    Deep Crab) PRZ-nya sudah melewati X, jadi SL harus beyond tepi PRZ terjauh,
    bukan X — kalau tidak SL malah berada di dalam zona entry."""
    p = cand["points"]
    X, A = p["X"]["price"], p["A"]["price"]
    prz = cand["prz"]
    buffer = abs(A - X) * settings.SL_BUFFER_XA
    if cand["direction"] == "bull":
        sl = min(X, prz["low"]) - buffer
    else:
        sl = max(X, prz["high"]) + buffer
    cand["sl"] = sl
    return sl


def calculate_tps(cand: dict) -> dict:
    """TP tiering dari retracement leg AD (D = mid PRZ)."""
    A = cand["points"]["A"]["price"]
    D = entry_price(cand)
    ad = A - D  # bull: positif (A di atas D)
    tps = {
        "tp1": D + ad * 0.382,
        "tp2": D + ad * 0.618,
        "tp3": D + ad * 1.0,
    }
    cand["tps"] = tps
    return tps


def calculate_rr(cand: dict) -> dict:
    entry = entry_price(cand)
    risk = abs(entry - cand["sl"])
    rr = {}
    for k, tp in cand["tps"].items():
        rr[k] = abs(tp - entry) / risk if risk > 0 else 0.0
    cand["rr"] = rr
    return rr


def price_distance_to_prz(cand: dict) -> float:
    """Jarak harga sekarang ke PRZ (0 kalau sudah di dalam), dalam fraksi
    harga. Negatif = harga sudah menembus PRZ menuju X."""
    px = cand["current_price"]
    prz = cand["prz"]
    if prz["low"] <= px <= prz["high"]:
        return 0.0
    if cand["direction"] == "bull":
        # harga turun menuju PRZ; di atas high → belum sampai
        return (px - prz["high"]) / px if px > prz["high"] else -(prz["low"] - px) / px
    return (prz["low"] - px) / px if px < prz["low"] else -(px - prz["high"]) / px


def enrich_levels(cand: dict) -> dict:
    """Isi sl/tps/rr/distance sekaligus. Wajib sudah ada cand["prz"]."""
    calculate_sl(cand)
    calculate_tps(cand)
    calculate_rr(cand)
    cand["prz_distance_pct"] = price_distance_to_prz(cand)
    cand["entry"] = entry_price(cand)
    return cand


def pre_grade(cand: dict) -> str:
    """Filter murah sebelum bayar Claude. Return "PASS" atau "FAIL", alasan
    disimpan di cand["pre_grade_reason"]."""
    reasons: list[str] = []
    X = cand["points"]["X"]["price"]
    px = cand["current_price"]

    if cand["deviation_max"] > TOLERANCE:
        reasons.append(f"ratio deviasi {cand['deviation_max']:.1%} > 5%")

    if cand["prz"]["confluence"] < 2:
        reasons.append("confluence PRZ < 2 level")

    # invalidasi: harga sudah lewat X
    if (cand["direction"] == "bull" and px < cand["sl"]) or (
        cand["direction"] == "bear" and px > cand["sl"]
    ):
        reasons.append("harga sudah lewat SL/X — pattern void")

    dist = cand["prz_distance_pct"]
    if cand["d_projected"]:
        if dist > settings.PRZ_APPROACH_PCT:
            reasons.append(f"harga masih {dist:.2%} dari PRZ (belum actionable)")
        if dist < -settings.PRZ_APPROACH_PCT:
            reasons.append("harga menembus PRZ terlalu jauh")

    if cand["rr"]["tp2"] < settings.MIN_RR_TP2_PREGRADE:
        reasons.append(f"R:R ke TP2 {cand['rr']['tp2']:.2f} < {settings.MIN_RR_TP2_PREGRADE}")

    cand["pre_grade_reason"] = "; ".join(reasons) if reasons else "ok"
    return "FAIL" if reasons else "PASS"


# ---------------------------------------------------------------------------
# HTF alignment
# ---------------------------------------------------------------------------

def _ema(values: list[float], period: int) -> float:
    k = 2 / (period + 1)
    e = values[0]
    for v in values[1:]:
        e = v * k + e * (1 - k)
    return e


def htf_trend(htf_candles: list[dict]) -> str:
    """'up' / 'down' / 'neutral' dari posisi close vs EMA20 vs EMA50."""
    closes = [c["close"] for c in htf_candles]
    if len(closes) < 30:
        return "neutral"
    e20, e50 = _ema(closes, 20), _ema(closes, 50)
    px = closes[-1]
    if px > e20 > e50:
        return "up"
    if px < e20 < e50:
        return "down"
    return "neutral"


def htf_alignment(cand: dict, trend: str) -> str:
    """aligned / neutral / counter. Bull pattern = beli di D → mau HTF up."""
    if trend == "neutral":
        return "neutral"
    want = "up" if cand["direction"] == "bull" else "down"
    return "aligned" if trend == want else "counter"


# ---------------------------------------------------------------------------
# Rule-based grade (weakest link)
# ---------------------------------------------------------------------------

def rule_grade(cand: dict) -> dict:
    factors: dict[str, str] = {}

    factors["pattern"] = PATTERNS[cand["pattern"]]["max_grade"]

    dev = cand["deviation_avg"]
    factors["precision"] = "A" if dev < ACCURATE_DEVIATION else ("B" if dev <= TOLERANCE else "C")

    conf = cand["prz"]["confluence"]
    fib, struct = cand["prz"]["fib_count"], cand["prz"]["structural_count"]
    if conf >= settings.CONFLUENCE_A or (fib >= 3 and struct >= 1):
        factors["confluence"] = "A"
    elif conf >= settings.CONFLUENCE_B:
        factors["confluence"] = "B"
    else:
        factors["confluence"] = "C"

    align = cand.get("htf_alignment", "neutral")
    factors["htf"] = {"aligned": "A", "neutral": "B", "counter": "C"}[align]

    rr2 = cand["rr"]["tp2"]
    factors["rr"] = "A" if rr2 >= settings.GRADE_RR_A else ("B" if rr2 >= settings.GRADE_RR_B else "C")

    grade = _worst(*factors.values())
    result = {"grade": grade, "factors": factors, "source": "rule"}
    cand["rule_grade"] = result
    return result
