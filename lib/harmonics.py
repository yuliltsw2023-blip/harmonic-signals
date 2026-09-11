"""XABCD extraction + pattern matching terhadap katalog."""

from __future__ import annotations

from config import settings
from config.patterns import PATTERNS, TOLERANCE


# ---------------------------------------------------------------------------
# Ratio helpers
# ---------------------------------------------------------------------------

def ratio_deviation(value: float, spec) -> float:
    """Deviasi relatif terhadap spec. Range → 0 kalau di dalam, kalau di luar
    jarak ke edge terdekat / edge. Fixed → |v - ideal| / ideal."""
    if isinstance(spec, tuple):
        lo, hi = spec
        if lo <= value <= hi:
            return 0.0
        edge = lo if value < lo else hi
        return abs(value - edge) / edge
    return abs(value - spec) / spec


def ideal_of(spec) -> float:
    if isinstance(spec, tuple):
        return (spec[0] + spec[1]) / 2
    return float(spec)


# ---------------------------------------------------------------------------
# Structure extraction
# ---------------------------------------------------------------------------

def extract_xabcd(pivots: list[dict], candles: list[dict]) -> list[dict]:
    """Ambil struktur X-A-B-C(-D) dari pivot yang sudah alternating.

    Dua jenis kandidat:
      * projected  — C = pivot terakhir, D belum terbentuk (harga sedang
                     menuju PRZ). d = None.
      * completed  — D = pivot terakhir, maksimal MAX_D_AGE_BARS bar lalu.
    Hanya struktur yang berakhir di pivot-pivot terbaru yang dipakai; pattern
    lama tidak actionable.
    """
    out: list[dict] = []
    n = len(pivots)
    last_idx = len(candles) - 1
    if n < 4:
        return out

    def direction_of(x: dict) -> str:
        # Bull pattern: X low, A high, D = buy zone (low). Bear kebalikan.
        return "bull" if x["type"] == "L" else "bear"

    # projected: X,A,B,C = 4 pivot terakhir
    x, a, b, c = pivots[-4:]
    out.append({
        "X": x, "A": a, "B": b, "C": c, "D": None,
        "direction": direction_of(x), "d_projected": True,
    })

    # completed: X,A,B,C,D = 5 pivot terakhir, D masih segar
    if n >= 5:
        x, a, b, c, d = pivots[-5:]
        if last_idx - d["idx"] <= settings.MAX_D_AGE_BARS:
            out.append({
                "X": x, "A": a, "B": b, "C": c, "D": d,
                "direction": direction_of(x), "d_projected": False,
            })
    return out


# ---------------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------------

def _leg(p: dict, q: dict) -> float:
    return abs(q["price"] - p["price"])


def compute_ratios(s: dict) -> dict:
    X, A, B, C, D = s["X"], s["A"], s["B"], s["C"], s["D"]
    xa, ab, bc = _leg(X, A), _leg(A, B), _leg(B, C)
    if xa == 0 or ab == 0 or bc == 0:
        return {}
    r = {
        "ab_xa": ab / xa,
        "bc_ab": bc / ab,
        "xc_xa": _leg(X, C) / xa,
    }
    if D is not None:
        r["cd_bc"] = _leg(C, D) / bc
        r["ad_xa"] = _leg(A, D) / xa
        xc = _leg(X, C)
        r["d_xc"] = _leg(C, D) / xc if xc else 0.0
    return r


def project_d(s: dict, pattern: str) -> float:
    """Harga D ideal dari requirement utama pattern."""
    X, A, C = s["X"]["price"], s["A"]["price"], s["C"]["price"]
    spec = PATTERNS[pattern]
    if pattern == "Cypher":
        # D = 0.786 retracement leg XC
        return C - (C - X) * spec["d_xc"]
    # D = ad_xa dari A menuju arah X (retracement <1, extension >1)
    return A + (X - A) * spec["ad_xa"]


def match_pattern(structures: list[dict]) -> list[dict]:
    """Cocokkan setiap struktur ke katalog. Return list match (bisa >1 per
    struktur kalau ambigu; pemanggil ambil deviasi terkecil)."""
    matches: list[dict] = []
    for s in structures:
        r = compute_ratios(s)
        if not r:
            continue
        # orientasi harus benar: bull → A > X, B < A, C > B
        X, A, B, C = (s[k]["price"] for k in "XABC")
        if s["direction"] == "bull" and not (A > X and B < A and C > B):
            continue
        if s["direction"] == "bear" and not (A < X and B > A and C < B):
            continue

        best_for_struct: list[dict] = []
        for name, spec in PATTERNS.items():
            checks = {"ab_xa": spec["ab_xa"]}
            if name == "Cypher":
                checks["xc_xa"] = spec["xc_xa"]
                if s["D"] is not None:
                    checks["d_xc"] = spec["d_xc"]
            else:
                checks["bc_ab"] = spec["bc_ab"]
                if s["D"] is not None:
                    checks["cd_bc"] = spec["cd_bc"]
                    checks["ad_xa"] = spec["ad_xa"]

            devs = {k: ratio_deviation(r[k], v) for k, v in checks.items()}
            if any(d > TOLERANCE for d in devs.values()):
                continue
            # Cypher: C harus melewati A (extension) — sanity
            if name == "Cypher" and not (
                (s["direction"] == "bull" and C > A) or (s["direction"] == "bear" and C < A)
            ):
                continue
            # Butterfly/Crab: D beyond X — cek untuk completed D
            if s["D"] is not None and spec.get("ad_xa", 0) > 1:
                Dp = s["D"]["price"]
                beyond = Dp < X if s["direction"] == "bull" else Dp > X
                if not beyond:
                    continue

            best_for_struct.append({
                "structure": s,
                "pattern": name,
                "ratios": r,
                "deviations": devs,
                "deviation_avg": sum(devs.values()) / len(devs),
                "deviation_max": max(devs.values()),
                "d_ideal": project_d(s, name),
            })

        if best_for_struct:
            best_for_struct.sort(key=lambda m: m["deviation_avg"])
            matches.append(best_for_struct[0])
    return matches


# ---------------------------------------------------------------------------
# Candidate assembly
# ---------------------------------------------------------------------------

def build_candidate(pair: str, timeframe: str, match: dict, candles: list[dict]) -> dict:
    """Gabungkan match + konteks pasar jadi dict kandidat yang dipakai oleh
    prz/grading/state/telegram. Level (PRZ, SL, TP) diisi oleh modul lain."""
    s = match["structure"]
    last = candles[-1]
    d_point = s["D"]
    d_date_src = d_point["datetime"] if d_point else s["C"]["datetime"]
    from config.pairs import asset_class
    return {
        "pair": pair,
        "asset_class": asset_class(pair),
        "timeframe": timeframe,
        "pattern": match["pattern"],
        "direction": s["direction"],
        "d_projected": s["d_projected"],
        "points": {
            "X": {"price": s["X"]["price"], "datetime": s["X"]["datetime"], "idx": s["X"]["idx"]},
            "A": {"price": s["A"]["price"], "datetime": s["A"]["datetime"], "idx": s["A"]["idx"]},
            "B": {"price": s["B"]["price"], "datetime": s["B"]["datetime"], "idx": s["B"]["idx"]},
            "C": {"price": s["C"]["price"], "datetime": s["C"]["datetime"], "idx": s["C"]["idx"]},
            "D": (
                {"price": d_point["price"], "datetime": d_point["datetime"], "idx": d_point["idx"]}
                if d_point else None
            ),
        },
        "d_ideal": match["d_ideal"],
        "ratios": match["ratios"],
        "deviations": match["deviations"],
        "deviation_avg": match["deviation_avg"],
        "deviation_max": match["deviation_max"],
        # d_date: dedup key. Completed → tanggal candle D. Projected → tanggal
        # C (bukan candle terakhir) supaya setup yang sama tidak dikirim ulang
        # tiap 4 jam selama harga masih di sekitar PRZ.
        "d_date": d_date_src[:10].replace("-", ""),
        "current_price": last["close"],
        "current_datetime": last["datetime"],
        "candles_count": len(candles),
    }
