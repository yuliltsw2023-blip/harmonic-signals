"""Swing pivot detection (fractal N kiri / N kanan) + zigzag filter."""

from __future__ import annotations


def atr(candles: list[dict], period: int = 14) -> float:
    """Average True Range sederhana (SMA dari TR)."""
    if len(candles) < 2:
        return 0.0
    trs = []
    for i in range(1, len(candles)):
        h, l, pc = candles[i]["high"], candles[i]["low"], candles[i - 1]["close"]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    window = trs[-period:]
    return sum(window) / len(window)


def find_pivots(
    highs: list[float],
    lows: list[float],
    left: int = 3,
    right: int = 3,
) -> list[dict]:
    """Pivot high = high[i] > semua high di `left` bar kiri & `right` bar kanan.
    Pivot low kebalikannya. Output urut idx, tipe "H"/"L".

    `right` bar terakhir belum bisa dikonfirmasi — sengaja tidak jadi pivot.
    """
    n = len(highs)
    out: list[dict] = []
    for i in range(left, n - right):
        h, l = highs[i], lows[i]
        is_high = all(h > highs[j] for j in range(i - left, i)) and all(
            h >= highs[j] for j in range(i + 1, i + right + 1)
        )
        is_low = all(l < lows[j] for j in range(i - left, i)) and all(
            l <= lows[j] for j in range(i + 1, i + right + 1)
        )
        if is_high:
            out.append({"idx": i, "price": h, "type": "H"})
        if is_low:
            out.append({"idx": i, "price": l, "type": "L"})
    return out


def zigzag(pivots: list[dict], min_move: float = 0.0) -> list[dict]:
    """Paksa alternasi H/L. Dua pivot sejenis berurutan → simpan yang lebih
    ekstrem. Leg lebih kecil dari `min_move` diabaikan (noise)."""
    out: list[dict] = []
    for p in pivots:
        if not out:
            out.append(p)
            continue
        last = out[-1]
        if p["type"] == last["type"]:
            better = (p["price"] > last["price"]) if p["type"] == "H" else (p["price"] < last["price"])
            if better:
                out[-1] = p
            continue
        if abs(p["price"] - last["price"]) < min_move:
            # leg terlalu kecil: pivot ini di-skip, tapi kalau pivot berikutnya
            # sejenis dengan `last` dan lebih ekstrem, loop di atas menangani.
            continue
        out.append(p)
    return out


def swing_pivots(candles: list[dict], left: int, right: int, min_leg_atr: float) -> list[dict]:
    """Pipeline lengkap: fractal → zigzag dengan filter ATR. Tiap pivot diberi
    datetime dari candle-nya."""
    highs = [c["high"] for c in candles]
    lows = [c["low"] for c in candles]
    raw = find_pivots(highs, lows, left, right)
    min_move = atr(candles) * min_leg_atr if min_leg_atr > 0 else 0.0
    zz = zigzag(raw, min_move)
    for p in zz:
        p["datetime"] = candles[p["idx"]]["datetime"]
    return zz
