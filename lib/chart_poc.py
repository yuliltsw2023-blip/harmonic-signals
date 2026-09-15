"""Chart PNG untuk sinyal POC pullback: candlestick + leg impulsif + VAH/POC/VAL
+ SL/TP. Headless matplotlib, dipakai lib/telegram.send_poc_signal."""

from __future__ import annotations

import io

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import Rectangle  # noqa: E402

from config.pairs import price_decimals  # noqa: E402
from lib.chart import BG, DOWN, ENTRY, GRID, SL, TP, TXT, UP  # noqa: E402

VA_FILL = "#5c6bc0"
POC_COL = "#ffca28"
LOOKBACK_BEFORE_LEG = 8
RIGHT_PAD = 10


def _idx_of(candles: list[dict], dt: str, default: int) -> int:
    for i, c in enumerate(candles):
        if c["datetime"] == dt:
            return i
    return default


def render_poc_chart(cand: dict, candles: list[dict]) -> bytes:
    d = price_decimals(cand["pair"])
    fmt = lambda x: f"{x:.{d}f}"
    n = len(candles)
    leg = cand["leg"]
    s_idx = _idx_of(candles, leg["start_datetime"], max(0, n - 60))
    e_idx = _idx_of(candles, leg["end_datetime"], n - 1)
    start = max(0, s_idx - LOOKBACK_BEFORE_LEG)
    view = candles[start:]
    xs = list(range(start, n))
    right_edge = n - 1 + RIGHT_PAD
    up = cand["direction"] == "bull"

    fig, ax = plt.subplots(figsize=(12, 6.5), dpi=130)
    fig.patch.set_facecolor(BG)
    ax.set_facecolor(BG)

    # value area (VAL–VAH) dari awal leg sampai kanan
    ax.add_patch(Rectangle((s_idx, cand["val"]), right_edge - s_idx, cand["vah"] - cand["val"],
                           facecolor=VA_FILL, alpha=0.18, edgecolor=VA_FILL, linewidth=0.8, zorder=1))
    # leg impulsif: shading vertikal tipis
    ax.axvspan(s_idx - 0.5, e_idx + 0.5, color=UP if up else DOWN, alpha=0.05, zorder=0)

    for x, c in zip(xs, view):
        color = UP if c["close"] >= c["open"] else DOWN
        ax.vlines(x, c["low"], c["high"], color=color, linewidth=0.8, zorder=2)
        lo, hi = sorted((c["open"], c["close"]))
        ax.add_patch(Rectangle((x - 0.35, lo), 0.7, (hi - lo) or 1e-9, facecolor=color,
                               edgecolor=color, linewidth=0.6, zorder=3))

    # garis leg: start → end
    ax.plot([s_idx, e_idx], [leg["start_price"], leg["end_price"]], color=TXT, linewidth=1.2,
            linestyle="--", alpha=0.7, zorder=4)

    def hline(y, color, label, ls="-", lw=1.0):
        ax.hlines(y, s_idx, right_edge, color=color, linewidth=lw, linestyle=ls, zorder=5)
        ax.text(right_edge - 0.3, y, f"{label} {fmt(y)}", color=color, fontsize=8, va="center",
                ha="right", zorder=8,
                bbox=dict(boxstyle="round,pad=0.2", facecolor=BG, edgecolor="none", alpha=0.85))

    hline(cand["vah"], VA_FILL, "VAH", ls=":")
    hline(cand["poc"], POC_COL, "POC / Entry", lw=1.6)
    hline(cand["val"], VA_FILL, "VAL", ls=":")
    hline(cand["sl"], SL, "SL", ls="--")
    hline(cand["tps"]["tp1"], TP, "TP1")
    hline(cand["tps"]["tp2"], TP, "TP2")

    ax.set_xlim(start - 1, right_edge + 1)
    ys = [c["low"] for c in view] + [c["high"] for c in view] + [cand["sl"], cand["tps"]["tp2"], cand["val"], cand["vah"]]
    lo, hi = min(ys), max(ys)
    pad = (hi - lo) * 0.06
    ax.set_ylim(lo - pad, hi + pad)

    step = max(1, len(view) // 8)
    ticks = list(range(start, n, step))
    ax.set_xticks(ticks)
    ax.set_xticklabels([candles[i]["datetime"][:10] for i in ticks], fontsize=7, color=TXT)
    ax.tick_params(axis="y", colors=TXT, labelsize=8)
    ax.yaxis.tick_right()
    ax.grid(color=GRID, linewidth=0.5, zorder=0)
    for s in ax.spines.values():
        s.set_color(GRID)

    side = "LONG" if up else "SHORT"
    g = cand.get("grade", {}).get("grade", "-")
    title = f"{cand['pair']}  POC PULLBACK  {cand['timeframe']}   ·   {side}   ·   Grade {g}   ·   {cand.get('stage_label', cand.get('stage', ''))}"
    ax.text(0.0, 1.055, title, transform=ax.transAxes, color=TXT, fontsize=12, fontweight="bold", va="bottom")
    ax.text(1.0, 1.055, side, transform=ax.transAxes, color=BG, fontsize=11, fontweight="bold",
            ha="right", va="bottom", zorder=9,
            bbox=dict(boxstyle="round,pad=0.35", facecolor=UP if up else DOWN, edgecolor="none"))
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
