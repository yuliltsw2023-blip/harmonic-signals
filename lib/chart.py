"""Render chart PNG untuk sinyal: candlestick + XABCD + PRZ + SL/TP.

Dipakai lib/telegram.send_signal (sendPhoto). Headless (Agg), tanpa GUI.
"""

from __future__ import annotations

import io

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import Rectangle  # noqa: E402

from config.pairs import price_decimals  # noqa: E402

# Palet gelap ala TradingView
BG = "#131722"
PANEL = "#1e222d"
GRID = "#2a2e39"
TXT = "#d1d4dc"
UP = "#26a69a"
DOWN = "#ef5350"
PATTERN = "#b39ddb"
PRZ_FILL = "#7e57c2"
SL = "#ef5350"
TP = "#26a69a"
ENTRY = "#ffb74d"

LOOKBACK_AFTER_X = 6     # bar sebelum X yang ikut ditampilkan
MIN_BARS = 70            # minimal bar yang ditampilkan
RIGHT_PAD = 14           # ruang kosong kanan untuk label & projected D


def render_signal_chart(cand: dict, candles: list[dict], grade: dict) -> bytes:
    d = price_decimals(cand["pair"])
    fmt = lambda x: f"{x:.{d}f}"
    p = cand["points"]
    prz = cand["prz"]
    bull = cand["direction"] == "bull"

    n = len(candles)
    start = max(0, min(p["X"]["idx"] - LOOKBACK_AFTER_X, n - MIN_BARS))
    view = candles[start:]
    xs = list(range(start, n))
    right_edge = n - 1 + RIGHT_PAD

    fig, ax = plt.subplots(figsize=(12, 6.5), dpi=130)
    fig.patch.set_facecolor(BG)
    ax.set_facecolor(BG)

    # --- candlestick -------------------------------------------------------
    for x, c in zip(xs, view):
        color = UP if c["close"] >= c["open"] else DOWN
        ax.vlines(x, c["low"], c["high"], color=color, linewidth=0.8, zorder=2)
        body_lo, body_hi = sorted((c["open"], c["close"]))
        h = body_hi - body_lo
        ax.add_patch(Rectangle((x - 0.35, body_lo), 0.7, h if h > 0 else 1e-9,
                               facecolor=color, edgecolor=color, linewidth=0.6, zorder=3))

    # --- PRZ zone (dari C ke kanan) -----------------------------------------
    ax.add_patch(Rectangle((p["C"]["idx"], prz["low"]), right_edge - p["C"]["idx"],
                           prz["high"] - prz["low"], facecolor=PRZ_FILL, alpha=0.22,
                           edgecolor=PRZ_FILL, linewidth=0.8, zorder=1))
    ax.text(p["C"]["idx"] + 0.5, prz["high"], f"PRZ {fmt(prz['low'])}–{fmt(prz['high'])}",
            color=PATTERN, fontsize=8, va="bottom", ha="left", zorder=6)

    # --- XABCD --------------------------------------------------------------
    pts = [(p[k]["idx"], p[k]["price"], k) for k in "XABC"]
    if p["D"]:
        pts.append((p["D"]["idx"], p["D"]["price"], "D"))
        d_x, d_price = p["D"]["idx"], p["D"]["price"]
    else:
        d_x, d_price = n - 1 + 4, cand["d_ideal"]
        pts.append((d_x, d_price, "D?"))

    px = [t[0] for t in pts]
    py = [t[1] for t in pts]
    ax.plot(px[:4], py[:4], color=PATTERN, linewidth=1.6, zorder=4)
    ax.plot(px[3:], py[3:], color=PATTERN, linewidth=1.6,
            linestyle="--" if not p["D"] else "-", zorder=4)
    # garis XB dan BD (segitiga harmonic klasik)
    ax.plot([px[0], px[2]], [py[0], py[2]], color=PATTERN, linewidth=0.8, alpha=0.6, zorder=4)
    ax.plot([px[2], px[4]], [py[2], py[4]], color=PATTERN, linewidth=0.8, alpha=0.6,
            linestyle="--" if not p["D"] else "-", zorder=4)
    ax.fill(px[:3] + [px[0]], py[:3] + [py[0]], color=PATTERN, alpha=0.08, zorder=1)
    ax.fill(px[2:] + [px[2]], py[2:] + [py[2]], color=PATTERN, alpha=0.08, zorder=1)

    for x, y, label in pts:
        is_high = (label in ("A", "C")) if bull else (label not in ("A", "C"))
        ax.annotate(label, (x, y), textcoords="offset points",
                    xytext=(0, 9 if is_high else -14), ha="center", fontsize=10,
                    fontweight="bold", color=PATTERN, zorder=7)
        ax.plot(x, y, "o", color=PATTERN, markersize=4, zorder=6)

    # --- levels -------------------------------------------------------------
    def hline(y, color, label, ls="-"):
        ax.hlines(y, p["C"]["idx"], right_edge, color=color, linewidth=1.0,
                  linestyle=ls, zorder=5)
        ax.text(right_edge - 0.3, y, f"{label} {fmt(y)}", color=color, fontsize=8,
                va="center", ha="right", zorder=8,
                bbox=dict(boxstyle="round,pad=0.2", facecolor=BG, edgecolor="none", alpha=0.85))

    hline(cand["sl"], SL, "SL", ls="--")
    hline(cand["entry"], ENTRY, "Entry", ls=":")
    hline(cand["tps"]["tp1"], TP, "TP1")
    hline(cand["tps"]["tp2"], TP, "TP2")
    hline(cand["tps"]["tp3"], TP, "TP3")

    # --- axes / cosmetics -------------------------------------------------------
    ax.set_xlim(start - 1, right_edge + 1)
    lows = [c["low"] for c in view] + [cand["sl"], cand["tps"]["tp3"], prz["low"], d_price]
    highs = [c["high"] for c in view] + [cand["sl"], cand["tps"]["tp3"], prz["high"], d_price]
    lo, hi = min(lows), max(highs)
    pad = (hi - lo) * 0.06
    ax.set_ylim(lo - pad, hi + pad)

    step = max(1, len(view) // 8)
    ticks = list(range(start, n, step))
    ax.set_xticks(ticks)
    ax.set_xticklabels([candles[i]["datetime"][:10] for i in ticks], fontsize=7, color=TXT,
                       rotation=0)
    ax.tick_params(axis="y", colors=TXT, labelsize=8)
    ax.yaxis.tick_right()
    ax.grid(color=GRID, linewidth=0.5, zorder=0)
    for s in ax.spines.values():
        s.set_color(GRID)

    status = "projected D" if cand["d_projected"] else "completed D"
    side = "LONG" if bull else "SHORT"
    title = (f"{cand['pair']}  {cand['pattern']} {'BULL' if bull else 'BEAR'}  {cand['timeframe']}"
             f"   ·   {side}   ·   Grade {grade['grade']}   ·   {status}")
    ax.text(1.0, 1.055, side, transform=ax.transAxes, color=BG, fontsize=11, fontweight="bold",
            ha="right", va="bottom", zorder=9,
            bbox=dict(boxstyle="round,pad=0.35", facecolor=UP if bull else DOWN, edgecolor="none"))
    ax.text(0.0, 1.055, title, transform=ax.transAxes, color=TXT, fontsize=12,
            fontweight="bold", va="bottom")
    ax.text(0.0, 1.012, f"harga {fmt(cand['current_price'])} @ {cand['current_datetime']} UTC"
            f"   |   R:R TP2 {cand['rr']['tp2']:.1f}:1   |   HTF {cand.get('htf_alignment', '-')}",
            transform=ax.transAxes, color="#8a8f9c", fontsize=8, va="bottom")
    fig.text(0.99, 0.01, "harmonic-signals · analisis edukatif, bukan sinyal buy/sell",
             color="#5c6170", fontsize=7, ha="right")

    fig.tight_layout(rect=(0, 0.02, 1, 0.94))
    buf = io.BytesIO()
    fig.savefig(buf, format="png", facecolor=BG)
    plt.close(fig)
    return buf.getvalue()
