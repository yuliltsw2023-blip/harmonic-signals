"""Gambar rencana trading: chart TradingView asli via chart-img (kalau
CHART_IMG_API_KEY valid), cadangan chart candlestick matplotlib sendiri."""

from __future__ import annotations

import io
import os
from datetime import datetime, timedelta, timezone

import requests

UTC = timezone.utc
CHART_IMG_URL = "https://api.chart-img.com/v2/tradingview/advanced-chart"
INTERVAL = {"M5": "5m", "M15": "15m"}
BARS_BACK = {"M5": 110, "M15": 110}
TF_SEC = {"M5": 300, "M15": 900}


def _iso(t: float) -> str:
    return datetime.fromtimestamp(t, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def chart_img(plan: dict, now: int, api_key: str | None = None) -> bytes:
    key = (api_key or os.environ.get("CHART_IMG_API_KEY", "")).strip()
    if not key:
        raise RuntimeError("CHART_IMG_API_KEY kosong")
    tf, sec = plan["tf"], TF_SEC[plan["tf"]]
    start = now - BARS_BACK[tf] * sec
    end = now + 30 * sec
    drawings = []
    if plan["action"] in ("buy", "sell"):
        drawings.append({
            "name": "Long Position" if plan["action"] == "buy" else "Short Position",
            "input": {"startDatetime": _iso(now), "endDatetime": _iso(now + plan["valid_hours"] * 3600),
                      "entryPrice": plan["entry"], "targetPrice": plan["tp2"], "stopPrice": plan["sl"]},
        })
        drawings.append({"name": "Horizontal Line", "input": {"price": plan["tp1"]},
                         "override": {"lineColor": "rgb(38,166,154)", "lineWidth": 1, "lineStyle": 2,
                                      "showLabel": True, "text": f"TP1 {plan['tp1']:.2f}"}})
    body = {
        "symbol": "OANDA:XAUUSD", "interval": INTERVAL[tf], "theme": "dark", "style": "candle",
        "width": 800, "height": 600, "timezone": "Asia/Jakarta",
        "range": {"from": _iso(start), "to": _iso(end)},
        "studies": [{"name": "Moving Average Exponential", "input": {"length": 20}},
                    {"name": "Moving Average Exponential", "input": {"length": 50}}],
        "drawings": drawings,
    }
    r = requests.post(CHART_IMG_URL, json=body, timeout=60,
                      headers={"x-api-key": key, "content-type": "application/json"})
    if r.status_code != 200 or not r.headers.get("content-type", "").startswith("image/"):
        raise RuntimeError(f"chart-img {r.status_code}: {r.text[:200]}")
    return r.content


def local_chart(plan: dict, bars: list[list[float]], now: int) -> bytes:
    """Chart candlestick sendiri (bukan TradingView) + zona entry/SL/TP."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Rectangle

    from .trade import ema

    tf, sec = plan["tf"], TF_SEC[plan["tf"]]
    all_closes = [b[4] for b in bars]
    e20_all, e50_all = ema(all_closes, 20), ema(all_closes, 50)
    bars = bars[-BARS_BACK[tf]:]
    e20, e50 = e20_all[-len(bars):], e50_all[-len(bars):]
    fig, ax = plt.subplots(figsize=(8, 6), dpi=100)
    fig.patch.set_facecolor("#131722")
    ax.set_facecolor("#131722")
    w = 0.6
    for i, (t, o, h, l, c) in enumerate(bars):
        col = "#26a69a" if c >= o else "#ef5350"
        ax.plot([i, i], [l, h], color=col, lw=0.8)
        ax.add_patch(Rectangle((i - w / 2, min(o, c)), w, max(abs(c - o), 0.01), color=col))
    ax.plot(range(len(bars)), e20, color="#f5c242", lw=1, label="EMA20")
    ax.plot(range(len(bars)), e50, color="#5b9cf6", lw=1, label="EMA50")
    n = len(bars)
    right = n + 25
    if plan["action"] in ("buy", "sell"):
        e, sl, t1, t2 = plan["entry"], plan["sl"], plan["tp1"], plan["tp2"]
        ax.add_patch(Rectangle((n - 0.5, min(e, t2)), 25, abs(t2 - e), color="#26a69a", alpha=0.18))
        ax.add_patch(Rectangle((n - 0.5, min(e, sl)), 25, abs(sl - e), color="#ef5350", alpha=0.18))
        for y, col, txt in ((e, "#e0b44c", "Entry"), (sl, "#ef5350", "SL"), (t1, "#26a69a", "TP1"), (t2, "#26a69a", "TP2")):
            ax.axhline(y, color=col, lw=0.9, ls="--", alpha=0.9)
            ax.text(right - 0.5, y, f" {txt} {y:.2f}", color=col, va="center", ha="right", fontsize=9,
                    fontweight="bold")
        lo = min(min(b[3] for b in bars), sl, t2)
        hi = max(max(b[2] for b in bars), sl, t2)
    else:
        lo, hi = min(b[3] for b in bars), max(b[2] for b in bars)
    pad = (hi - lo) * 0.06
    ax.set_ylim(lo - pad, hi + pad)
    ax.set_xlim(-1, right)
    step = max(1, n // 6)
    ticks = list(range(0, n, step))
    ax.set_xticks(ticks)
    ax.set_xticklabels([datetime.fromtimestamp(bars[i][0], UTC).astimezone(
        timezone(timedelta(hours=7))).strftime("%d/%m %H:%M") for i in ticks], fontsize=8)
    ax.tick_params(colors="#9aa0a6")
    ax.yaxis.tick_right()
    for s in ax.spines.values():
        s.set_color("#2a2e39")
    ax.grid(color="#1f2330", lw=0.6)
    act = {"buy": "BUY", "sell": "SELL", "no_trade": "TIDAK ADA SETUP"}[plan["action"]]
    ax.set_title(f"XAU/USD {tf} · {plan['style'].upper()} · {act}", color="#e8e6e3", fontsize=12, loc="left")
    ax.legend(loc="upper left", fontsize=8, facecolor="#131722", labelcolor="#9aa0a6", framealpha=0.6)
    fig.text(0.01, 0.01, "chart cadangan (bukan TradingView)", color="#5f6368", fontsize=7)
    buf = io.BytesIO()
    fig.tight_layout()
    fig.savefig(buf, format="png", facecolor=fig.get_facecolor())
    plt.close(fig)
    return buf.getvalue()


def render(plan: dict, bars: list[list[float]], now: int, errors: list[str]) -> tuple[bytes, str]:
    """→ (png, sumber) — 'tradingview' atau 'cadangan'."""
    try:
        return chart_img(plan, now), "tradingview"
    except Exception as e:  # noqa: BLE001
        errors.append(f"chart-img: {str(e)[:80]}")
    return local_chart(plan, bars, now), "cadangan"
