"""POC Pullback screener — strategi entry kedua (skill `poc-pullback-entry`).

Pure function: candles → kandidat POC pullback (atau None).
  1. Bias dari 2 swing high + 2 swing low terakhir (HH+HL bull, LH+LL bear).
  2. Leg impulsif: swing low terbaru → high tertinggi setelahnya (bull); mirror bear.
  3. Fixed Range profile di leg itu → POC / VAH / VAL. Bobot = volume kalau
     data punya volume (saham via Yahoo), kalau tidak TPO (1 per bar,
     time-at-price ala Market Profile) — Twelve Data free tidak kasih volume.
  4. Stage harga vs Value Area: waiting → approaching → in_va → reacted.
     Sinyal hanya untuk approaching / in_va / reacted.
Grade rule-based weakest-link; reaksi & news tetap dicek manual (analisis
edukatif, bukan sinyal buy/sell).
"""

from __future__ import annotations

from config import settings
from config.pairs import asset_class
from lib.grading import _worst
from lib.pivots import atr, swing_pivots

SIGNAL_STAGES = ("approaching", "in_va", "reacted")

STAGE_LABEL = {
    "waiting": "MENUNGGU PULLBACK ke Value Area",
    "approaching": "MENDEKATI Value Area — siapkan watchlist",
    "in_va": "DI DALAM Value Area — cek candle reaksi",
    "reacted": "REAKSI dari Value Area — konfirmasi entry",
    "impulse": "impuls masih berjalan, belum pullback",
    "below_va": "tembus Value Area — tunggu reaksi kedua",
    "left_va": "sudah meninggalkan Value Area tanpa entry",
    "continued": "sudah lanjut melewati swing — missed",
    "broken": "struktur patah (close di luar swing awal leg)",
}


# ---------------------------------------------------------------------------
# Profile
# ---------------------------------------------------------------------------

def build_profile(leg: list[dict], bins: int, va_pct: float) -> dict:
    lo = min(c["low"] for c in leg)
    hi = max(c["high"] for c in leg)
    rng = hi - lo
    if rng <= 0:
        raise ValueError("leg range 0")
    use_volume = all("volume" in c for c in leg) and sum(c.get("volume", 0.0) for c in leg) > 0
    size = rng / bins
    vols = [0.0] * bins
    total = 0.0
    for c in leg:
        w = c["volume"] if use_volume else 1.0
        lo_b = max(0, min(bins - 1, int((c["low"] - lo) / size)))
        hi_b = max(0, min(bins - 1, int((c["high"] - lo) / size)))
        span = hi_b - lo_b + 1
        for b in range(lo_b, hi_b + 1):
            vols[b] += w / span
        total += w
    poc_bin = max(range(bins), key=lambda b: vols[b])
    acc = vols[poc_bin]
    up = dn = poc_bin
    while acc < total * va_pct and (up < bins - 1 or dn > 0):
        v_up = vols[up + 1] if up < bins - 1 else -1.0
        v_dn = vols[dn - 1] if dn > 0 else -1.0
        if v_up >= v_dn:
            up += 1
            acc += v_up
        else:
            dn -= 1
            acc += v_dn
    return {
        "source": "volume" if use_volume else "tpo",
        "bins": bins,
        "poc": lo + (poc_bin + 0.5) * size,
        "vah": lo + (up + 1) * size,
        "val": lo + dn * size,
        "va_pct": va_pct,
        "leg_low": lo,
        "leg_high": hi,
    }


# ---------------------------------------------------------------------------
# Structure
# ---------------------------------------------------------------------------

def _structure(pivots: list[dict]) -> dict | None:
    hs = [p for p in pivots if p["type"] == "H"][-2:]
    ls = [p for p in pivots if p["type"] == "L"][-2:]
    if len(hs) < 2 or len(ls) < 2:
        return None
    prev_h, last_h = hs
    prev_l, last_l = ls
    if last_h["price"] > prev_h["price"] and last_l["price"] > prev_l["price"]:
        bias = "bull"
    elif last_h["price"] < prev_h["price"] and last_l["price"] < prev_l["price"]:
        bias = "bear"
    else:
        bias = None
    return {"bias": bias, "prev_h": prev_h, "last_h": last_h, "prev_l": prev_l, "last_l": last_l}


def _reactions(candles: list[dict], bias: str, poc: float) -> list[str]:
    """Sinyal reaksi di candle terakhir (yang sudah close)."""
    if len(candles) < 2:
        return []
    c, p = candles[-1], candles[-2]
    rng = c["high"] - c["low"]
    out: list[str] = []
    if rng <= 0:
        return out
    body_lo, body_hi = min(c["open"], c["close"]), max(c["open"], c["close"])
    if bias == "bull":
        if (body_lo - c["low"]) / rng >= 0.5 and c["close"] > poc:
            out.append("rejection wick bawah ≥50% & close > POC")
        if c["close"] > c["open"] and p["close"] < p["open"] and c["close"] > p["open"] and c["open"] <= p["close"] and c["close"] > poc:
            out.append("bullish engulfing")
    else:
        if (c["high"] - body_hi) / rng >= 0.5 and c["close"] < poc:
            out.append("rejection wick atas ≥50% & close < POC")
        if c["close"] < c["open"] and p["close"] > p["open"] and c["close"] < p["open"] and c["open"] >= p["close"] and c["close"] < poc:
            out.append("bearish engulfing")
    return out


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def analyze_poc(pair: str, timeframe: str, candles: list[dict]) -> dict | None:
    """Return kandidat POC (dict) atau None kalau struktur tidak memenuhi
    syarat dasar. cand["pre_grade"] PASS/FAIL + alasan di pre_grade_reason."""
    if len(candles) < 30:
        return None
    n = settings.POC_PIVOT.get(timeframe, 5)
    pivots = swing_pivots(candles, n, n, settings.MIN_LEG_ATR)
    st = _structure(pivots)
    if st is None:
        return None
    last_idx = len(candles) - 1
    bias = st["bias"]
    reasons: list[str] = []

    # Leg impulsif. Bull: dari swing low yang MEMULAI impuls ke swing high
    # terakhir. Kalau pivot terbaru adalah low SETELAH swing high (= pullback
    # low yang sudah terkonfirmasi) dan belum ada HH baru, leg tetap yang lama;
    # kalau sudah ada high baru di atas last_h, itu impuls baru dari low tsb.
    lh, ll, ph_, pl_ = st["last_h"], st["last_l"], st["prev_h"], st["prev_l"]
    if bias == "bull" or (bias is None and ll["idx"] > lh["idx"]):
        up = True
        if ll["idx"] < lh["idx"]:
            start = ll["idx"]
        elif max(c["high"] for c in candles[ll["idx"]:]) > lh["price"]:
            start = ll["idx"]
        else:
            start = pl_["idx"] if pl_["idx"] < lh["idx"] else ll["idx"]
        end = max(range(start, last_idx + 1), key=lambda i: candles[i]["high"])
    else:
        up = False
        if lh["idx"] < ll["idx"]:
            start = lh["idx"]
        elif min(c["low"] for c in candles[lh["idx"]:]) < ll["price"]:
            start = lh["idx"]
        else:
            start = ph_["idx"] if ph_["idx"] < ll["idx"] else lh["idx"]
        end = min(range(start, last_idx + 1), key=lambda i: candles[i]["low"])
    leg = candles[start:end + 1]
    leg_bars = len(leg)
    if leg_bars < 3 or max(c["high"] for c in leg) <= min(c["low"] for c in leg):
        return None

    prof = build_profile(leg, settings.POC_BINS, settings.POC_VA_PCT)
    poc, vah, val = prof["poc"], prof["vah"], prof["val"]
    leg_low, leg_high = prof["leg_low"], prof["leg_high"]
    rng = leg_high - leg_low
    depth = (leg_high - poc) / rng if up else (poc - leg_low) / rng

    last = candles[-1]
    px = last["close"]
    ap = settings.POC_APPROACH_PCT[asset_class(pair)] * settings.tf_scale(timeframe)
    after = candles[end + 1:]
    pb_ext = None
    if after:
        pb_ext = min(c["low"] for c in after) if up else max(c["high"] for c in after)

    # stage
    if up:
        if px < leg_low:
            stage = "broken"
        elif end == last_idx:
            stage = "impulse"
        elif px > leg_high:
            stage = "continued"
        elif pb_ext is not None and pb_ext < val and px < val:
            stage = "below_va"
        elif pb_ext is not None and pb_ext <= vah:
            if px <= vah:
                stage = "in_va"
            else:
                stage = "reacted" if (px - vah) / px <= ap else "left_va"
        else:
            stage = "approaching" if (px - vah) / px <= ap else "waiting"
        dist = max(0.0, (px - vah) / px)
    else:
        if px > leg_high:
            stage = "broken"
        elif end == last_idx:
            stage = "impulse"
        elif px < leg_low:
            stage = "continued"
        elif pb_ext is not None and pb_ext > vah and px > vah:
            stage = "below_va"
        elif pb_ext is not None and pb_ext >= val:
            if px >= val:
                stage = "in_va"
            else:
                stage = "reacted" if (val - px) / px <= ap else "left_va"
        else:
            stage = "approaching" if (val - px) / px <= ap else "waiting"
        dist = max(0.0, (val - px) / px)

    reactions = _reactions(candles, "bull" if up else "bear", poc) if stage in ("in_va", "reacted") else []

    # level
    buf = settings.POC_SL_ATR[asset_class(pair)] * atr(candles)
    if up:
        sl_cons, sl_aggr = leg_low - buf, val - buf
        tp1, tp2, tp3 = leg_high, leg_low + 1.272 * rng, leg_low + 1.618 * rng
    else:
        sl_cons, sl_aggr = leg_high + buf, vah + buf
        tp1, tp2, tp3 = leg_low, leg_high - 1.272 * rng, leg_high - 1.618 * rng
    tps = {"tp1": tp1, "tp2": tp2, "tp3": tp3}

    def _rr(sl: float) -> dict:
        risk = abs(poc - sl)
        return {k: (abs(tp - poc) / risk if risk > 0 else 0.0) for k, tp in tps.items()}

    rr = _rr(sl_cons)
    rr_aggr = _rr(sl_aggr)
    # Skill: minimum 2:1 ke TP1 dengan SL agresif ATAU ke TP2 dengan SL
    # konservatif — ambil yang lebih baik sebagai R:R efektif untuk grading.
    rr_eff = max(rr["tp2"], rr_aggr["tp1"])

    # pre-grade
    if bias is None:
        reasons.append("struktur UNCLEAR (bukan HH+HL / LH+LL)")
    if leg_bars < settings.POC_MIN_LEG_BARS:
        reasons.append(f"leg {leg_bars} candle < {settings.POC_MIN_LEG_BARS}")
    leg_atr = rng / atr(candles) if atr(candles) > 0 else 0.0
    if settings.POC_MIN_LEG_ATR > 0 and leg_atr < settings.POC_MIN_LEG_ATR:
        reasons.append(f"leg {leg_atr:.1f}×ATR < {settings.POC_MIN_LEG_ATR}")
    if stage not in SIGNAL_STAGES:
        reasons.append(f"stage {stage}")
    if not (settings.POC_DEPTH_MIN <= depth <= settings.POC_DEPTH_MAX):
        reasons.append(f"kedalaman POC {depth:.2f} di luar {settings.POC_DEPTH_MIN}–{settings.POC_DEPTH_MAX}")
    if rr_eff < settings.MIN_RR_TP2_PREGRADE:
        reasons.append(f"R:R efektif {rr_eff:.2f} < {settings.MIN_RR_TP2_PREGRADE} "
                       f"(TP2/SL swing {rr['tp2']:.2f}, TP1/SL VA {rr_aggr['tp1']:.2f})")

    return {
        "kind": "poc",
        "pair": pair,
        "asset_class": asset_class(pair),
        "timeframe": timeframe,
        "direction": "bull" if up else "bear",
        "bias": bias,
        "structure": {
            "prev_h": st["prev_h"]["price"], "last_h": st["last_h"]["price"],
            "prev_l": st["prev_l"]["price"], "last_l": st["last_l"]["price"],
        },
        "leg": {
            "start_price": leg_low if up else leg_high,
            "start_datetime": candles[start]["datetime"],
            "end_price": leg_high if up else leg_low,
            "end_datetime": candles[end]["datetime"],
            "bars": leg_bars,
            "low": leg_low, "high": leg_high,
        },
        "profile": prof,
        "poc": poc, "vah": vah, "val": val,
        "depth": depth,
        "leg_atr": leg_atr,
        "depth_label": ("ideal" if settings.POC_DEPTH_IDEAL[0] <= depth <= settings.POC_DEPTH_IDEAL[1]
                        else "dangkal" if depth < settings.POC_DEPTH_IDEAL[0] else "dalam"),
        "stage": stage,
        "stage_label": STAGE_LABEL[stage],
        "distance_pct": dist,
        "pullback_extreme": pb_ext,
        "reactions": reactions,
        "entry": poc,
        "sl": sl_cons,
        "sl_aggressive": sl_aggr,
        "tps": tps,
        "rr": rr,
        "rr_aggressive": rr_aggr,
        "rr_eff": rr_eff,
        "leg_date": candles[start]["datetime"][:10].replace("-", ""),
        "current_price": px,
        "current_datetime": last["datetime"],
        "pre_grade": "FAIL" if reasons else "PASS",
        "pre_grade_reason": "; ".join(reasons) if reasons else "ok",
    }


def poc_alignment(cand: dict, trend: str) -> str:
    if trend == "neutral":
        return "neutral"
    want = "up" if cand["direction"] == "bull" else "down"
    return "aligned" if trend == want else "counter"


def rule_grade_poc(cand: dict) -> dict:
    """Weakest link, mengikuti rubric skill poc-pullback-entry. Reaksi 0 tidak
    menjatuhkan ke C karena screener memang memberi tahu SEBELUM reaksi —
    label stage sudah bilang 'cek candle reaksi'."""
    f: dict[str, str] = {}
    lo, hi = settings.POC_DEPTH_IDEAL
    f["depth"] = "A" if lo <= cand["depth"] <= hi else "B"
    f["leg"] = "A" if cand["leg"]["bars"] >= settings.POC_LEG_BARS_A else "B"
    f["htf"] = {"aligned": "A", "neutral": "B", "counter": "C"}[cand.get("htf_alignment", "neutral")]
    rr_eff = cand["rr_eff"]
    f["rr"] = "A" if rr_eff >= settings.GRADE_RR_A else ("B" if rr_eff >= settings.GRADE_RR_B else "C")
    f["reaction"] = "A" if len(cand["reactions"]) >= 2 else "B"
    f["profile"] = "A" if cand["profile"]["source"] == "volume" else "B"
    grade = _worst(*f.values())
    reasoning = [
        f"Kedalaman POC {cand['depth']:.2f} ({cand['depth_label']})",
        f"Leg {cand['leg']['bars']} candle",
        f"HTF {cand.get('htf_timeframe', '-')}: {cand.get('htf_alignment', 'neutral')}",
        f"R:R efektif {rr_eff:.1f}:1 (TP2 dgn SL swing {cand['rr']['tp2']:.1f}:1 · TP1 dgn SL VA {cand['rr_aggressive']['tp1']:.1f}:1)",
        ("Reaksi: " + ", ".join(cand["reactions"])) if cand["reactions"] else "Reaksi: belum ada — tunggu candle close",
        "Profile: volume asli" if cand["profile"]["source"] == "volume" else "Profile: TPO (time-at-price, tanpa volume) — maks Grade B",
    ]
    result = {"grade": grade, "factors": f, "reasoning": reasoning, "source": "rule"}
    cand["grade"] = result
    return result
