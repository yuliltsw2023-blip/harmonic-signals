"""Candle sintetis yang membentuk pattern harmonic sempurna, untuk test &
dry run tanpa API key."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone


def _walk(path: list[tuple[float, int]], start: datetime, step_hours: int = 4,
          wick: float = 0.0003) -> list[dict]:
    """path = [(target_price, bars)] — interpolasi linear antar target,
    candle di-generate dengan wick kecil supaya pivot jelas di target."""
    candles: list[dict] = []
    t = start
    price = path[0][0]
    for target, bars in path[1:]:
        for i in range(1, bars + 1):
            nxt = price + (target - price) * i / bars
            o, c = price + (nxt - price) * 0.1, nxt
            hi, lo = max(o, c) + wick * 0.3, min(o, c) - wick * 0.3
            candles.append({"datetime": t.strftime("%Y-%m-%d %H:%M:%S"), "open": o,
                            "high": hi, "low": lo, "close": c})
            t += timedelta(hours=step_hours)
        price = target
    return candles


def synthetic_bat(bull: bool = True, base: float = 1.1000, projected: bool = True,
                  ab_xa: float = 0.45, bc_ab: float = 0.6, ad_xa: float = 0.886) -> list[dict]:
    """Bull Bat: X low → A high → B (0.45 XA) → C (0.6 AB) → D (0.886 XA)."""
    xa = 0.0300
    sign = 1 if bull else -1
    X = base
    A = X + sign * xa
    B = A - sign * xa * ab_xa
    C = B + sign * abs(A - B) * bc_ab
    D = A - sign * xa * ad_xa
    start = datetime(2026, 6, 1, tzinfo=timezone.utc)
    # pre-noise supaya ada >50 candle & pivot sebelumnya untuk structural
    pre = [(X + sign * 0.0100, 0), (X + sign * 0.0180, 10), (X + sign * 0.0050, 10),
           (X + sign * 0.0200, 12), (X + sign * 0.0020, 8)]
    path = pre + [(X, 8), (A, 14), (B, 10), (C, 9)]
    if projected:
        # harga sedang turun menuju PRZ, berhenti tepat di tepi PRZ
        path.append((D + sign * 0.0006, 8))
        # 3 bar terakhir stagnan supaya pivot C terkonfirmasi (right=3)
        path.append((D + sign * 0.0005, 3))
    else:
        path.append((D, 9))
        path.append((D + sign * 0.0040, 4))
    return _walk(path, start)


def synthetic_gartley(bull: bool = True, base: float = 1.2500) -> list[dict]:
    """Bull Gartley: B=0.618 XA, C=0.5 AB, D projected 0.786 XA."""
    return synthetic_bat(bull=bull, base=base, projected=True, ab_xa=0.618, bc_ab=0.5, ad_xa=0.786)


def synthetic_random_walk(n: int = 200, base: float = 1.3000, seed: int = 7) -> list[dict]:
    import random
    rnd = random.Random(seed)
    start = datetime(2026, 5, 1, tzinfo=timezone.utc)
    out, price, t = [], base, start
    for _ in range(n):
        c = price + rnd.gauss(0, 0.0015)
        hi, lo = max(price, c) + abs(rnd.gauss(0, 0.0005)), min(price, c) - abs(rnd.gauss(0, 0.0005))
        out.append({"datetime": t.strftime("%Y-%m-%d %H:%M:%S"), "open": price, "high": hi, "low": lo, "close": c})
        price, t = c, t + timedelta(hours=4)
    return out
