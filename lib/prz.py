"""Potential Reversal Zone: kumpulan Fib level yang converge di sekitar D."""

from __future__ import annotations

from config import settings
from config.pairs import round_step
from config.patterns import AB_CD_PROJECTIONS, PATTERNS


def _fib_levels(cand: dict) -> list[dict]:
    p = cand["points"]
    X, A, B, C = (p[k]["price"] for k in "XABC")
    bull = cand["direction"] == "bull"
    spec = PATTERNS[cand["pattern"]]
    levels: list[dict] = []

    def add(name: str, price: float, kind: str = "fib"):
        levels.append({"name": name, "price": price, "kind": kind})

    if cand["pattern"] == "Cypher":
        add(f"{spec['d_xc']:.3f} XC", C - (C - X) * spec["d_xc"])
        # Alternatif: 0.786 & 0.886 XC sebagai band
        add("0.886 XC", C - (C - X) * 0.886)
    else:
        add(f"{spec['ad_xa']:.3f} XA", A + (X - A) * spec["ad_xa"])
        lo, hi = spec["cd_bc"]
        # extension BC: D = C ± ratio * |BC|
        bc = abs(C - B)
        sign = -1 if bull else 1  # bull: D di bawah C
        add(f"{lo:.3f} BC", C + sign * bc * lo)
        add(f"{hi:.3f} BC", C + sign * bc * hi)
        mid = (lo + hi) / 2
        add(f"{mid:.3f} BC", C + sign * bc * mid)

    # AB=CD projections
    ab = abs(A - B)
    sign = -1 if bull else 1
    for k in AB_CD_PROJECTIONS:
        add(f"{k:.3f} AB=CD", C + sign * ab * k)
    return levels


def _structural_levels(cand: dict, pivots: list[dict] | None) -> list[dict]:
    """Previous swing high/low + round number yang dekat D."""
    out: list[dict] = []
    if pivots:
        bull = cand["direction"] == "bull"
        want = "L" if bull else "H"
        x_idx = cand["points"]["X"]["idx"]
        prior = [p for p in pivots if p["idx"] < x_idx and p["type"] == want]
        for p in prior[-settings.STRUCTURAL_LOOKBACK_PIVOTS:]:
            out.append({"name": f"prev swing {p['datetime'][:10]}", "price": p["price"], "kind": "structural"})
    # round number psikologis per asset (forex 0.0100/1.00, XAU 50, BTC 1000)
    d = cand["d_ideal"]
    step = round_step(cand["pair"])
    rn = round(d / step) * step
    out.append({"name": f"round {rn:g}", "price": rn, "kind": "structural"})
    return out


def construct_prz(cand: dict, pivots: list[dict] | None = None) -> dict:
    """Bangun PRZ dari level yang jatuh dalam band PRZ_BAND_PCT di sekitar
    level utama pattern. Mengisi cand["prz"] dan mengembalikannya."""
    primary = cand["d_ideal"]
    band = primary * settings.asset_params(cand["pair"], cand.get("timeframe"))["prz_band"]
    fib = _fib_levels(cand)
    structural = _structural_levels(cand, pivots)

    clustered = [lv for lv in fib if abs(lv["price"] - primary) <= band]
    struct_hit = [lv for lv in structural if abs(lv["price"] - primary) <= band]

    # Level utama selalu ada (index 0); pastikan tidak dobel
    seen = set()
    levels = []
    for lv in clustered + struct_hit:
        key = (lv["name"], round(lv["price"], 6))
        if key in seen:
            continue
        seen.add(key)
        levels.append(lv)

    prices = [lv["price"] for lv in levels] or [primary]
    prz = {
        "low": min(prices),
        "high": max(prices),
        "mid": (min(prices) + max(prices)) / 2,
        "levels": levels,
        "fib_count": len(clustered),
        "structural_count": len(struct_hit),
        "confluence": len(clustered) + len(struct_hit),
        "width_pct": (max(prices) - min(prices)) / primary,
    }
    cand["prz"] = prz
    return prz
