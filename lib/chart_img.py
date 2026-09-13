"""Chart TradingView asli via chart-img.com (render server-side).

Dipakai kalau env CHART_IMG_API_KEY terisi; kalau gagal, lib/telegram
fallback ke chart matplotlib (lib/chart.py). Free tier: 50 req/hari,
800x600, watermark kecil.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import requests

API_URL = "https://api.chart-img.com/v2/tradingview/advanced-chart"
LAYOUT_URL = "https://api.chart-img.com/v2/tradingview/layout-chart/{layout_id}"
INTERVAL_OF = {"H1": "1h", "H4": "4h", "D1": "1D"}
BAR_HOURS = {"H1": 1, "H4": 4, "D1": 24}

PATTERN = "rgb(179,157,219)"
PRZ_LINE = "rgb(126,87,194)"
PRZ_FILL = "rgba(126,87,194,0.25)"
SL = "rgb(239,83,80)"
TP = "rgb(38,166,154)"
ENTRY = "rgb(255,183,77)"


def _iso(dt_str: str) -> str:
    """'2026-09-08 01:00:00' (UTC) → '2026-09-08T01:00:00Z'."""
    return dt_str.replace(" ", "T") + ("Z" if not dt_str.endswith("Z") else "")


def _parse(dt_str: str) -> datetime:
    return datetime.strptime(dt_str[:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)


def tv_symbol(pair: str, exchange: str | None = None) -> str:
    from config.pairs import is_stock, tv_exchange
    exchange = exchange or tv_exchange(pair)
    # Saham format Yahoo: "BBCA.JK" → "IDX:BBCA"; forex "EUR/USD" → "OANDA:EURUSD"
    base = pair.split(".")[0] if is_stock(pair) else pair.replace("/", "")
    return f"{exchange}:{base}"


def build_request(cand: dict, grade: dict) -> dict:
    p = cand["points"]
    tf = cand["timeframe"]
    bar = timedelta(hours=BAR_HOURS[tf])
    last = _parse(cand["current_datetime"])
    x_t, a_t, b_t, c_t = (_parse(p[k]["datetime"]) for k in "XABC")
    if p["D"]:
        d_t, d_price = _parse(p["D"]["datetime"]), p["D"]["price"]
    else:
        d_t, d_price = last + bar * 4, cand["d_ideal"]
    prz = cand["prz"]
    right = last + bar * 14
    iso = lambda dt: dt.strftime("%Y-%m-%dT%H:%M:%SZ")

    def tl(t1, p1, t2, p2, dashed=False):
        return {"name": "Trend Line",
                "input": {"startDatetime": iso(t1), "endDatetime": iso(t2), "startPrice": p1, "endPrice": p2},
                "override": {"lineColor": PATTERN, "lineWidth": 2, **({"lineStyle": 2} if dashed else {})}}

    def hl(price, color, text, dashed=False):
        return {"name": "Horizontal Line", "input": {"price": price},
                "override": {"lineColor": color, "lineWidth": 1, "showLabel": True, "text": text,
                             **({"lineStyle": 2} if dashed else {})}}

    def txt(t, price, text):
        return {"name": "Text", "input": {"datetime": iso(t), "price": price, "text": text},
                "override": {"textColor": PATTERN, "fontSize": 16, "bold": True}}

    d = 3 if cand["pair"].endswith("JPY") else 5
    f = lambda v: f"{v:.{d}f}"
    drawings = [
        tl(x_t, p["X"]["price"], a_t, p["A"]["price"]),
        tl(a_t, p["A"]["price"], b_t, p["B"]["price"]),
        tl(b_t, p["B"]["price"], c_t, p["C"]["price"]),
        tl(c_t, p["C"]["price"], d_t, d_price, dashed=cand["d_projected"]),
        {"name": "Rectangle",
         "input": {"startDatetime": iso(c_t), "endDatetime": iso(right),
                   "topPrice": prz["high"], "bottomPrice": prz["low"]},
         "override": {"lineColor": PRZ_LINE, "backgroundColor": PRZ_FILL, "lineWidth": 1}},
        hl(cand["sl"], SL, f"SL {f(cand['sl'])}", dashed=True),
        hl(cand["entry"], ENTRY, f"Entry {f(cand['entry'])}", dashed=True),
        hl(cand["tps"]["tp1"], TP, f"TP1 {f(cand['tps']['tp1'])}"),
        hl(cand["tps"]["tp2"], TP, f"TP2 {f(cand['tps']['tp2'])}"),
        hl(cand["tps"]["tp3"], TP, f"TP3 {f(cand['tps']['tp3'])}"),
        txt(x_t, p["X"]["price"], "X"), txt(a_t, p["A"]["price"], "A"),
        txt(b_t, p["B"]["price"], "B"), txt(c_t, p["C"]["price"], "C"),
        txt(d_t, d_price, "D" if p["D"] else "D?"),
    ]
    return {
        "symbol": tv_symbol(cand["pair"]),
        "interval": INTERVAL_OF[tf],
        "theme": "dark",
        "style": "candle",
        "width": int(os.environ.get("CHART_IMG_WIDTH", "800")),
        "height": int(os.environ.get("CHART_IMG_HEIGHT", "600")),
        "timezone": "Etc/UTC",
        "range": {"from": iso(x_t - bar * 12), "to": iso(right)},
        "drawings": drawings,
    }


def render_chart_img(cand: dict, grade: dict, api_key: str | None = None, timeout: float = 45) -> bytes:
    """PNG bytes dari chart-img. Raise kalau key kosong atau API error."""
    api_key = (api_key or os.environ.get("CHART_IMG_API_KEY", "")).strip()
    if not api_key:
        raise RuntimeError("CHART_IMG_API_KEY kosong")
    resp = requests.post(API_URL, json=build_request(cand, grade),
                         headers={"x-api-key": api_key, "content-type": "application/json"},
                         timeout=timeout)
    if resp.status_code != 200 or not resp.headers.get("content-type", "").startswith("image/"):
        raise RuntimeError(f"chart-img {resp.status_code}: {resp.text[:300]}")
    return resp.content


def render_layout_chart(cand: dict, api_key: str | None = None, layout_id: str | None = None,
                        timeout: float = 120) -> bytes:
    """Screenshot layout TradingView milik user (shared) — indikator Pine
    Harmonic XABCD di layout itulah yang menggambar pattern, PRZ, SL/TP.
    Tidak kena limit 3 drawing. Butuh CHART_IMG_LAYOUT_ID (layout harus
    di-set "Share layout" di TradingView)."""
    api_key = (api_key or os.environ.get("CHART_IMG_API_KEY", "")).strip()
    layout_id = (layout_id or os.environ.get("CHART_IMG_LAYOUT_ID", "")).strip()
    if not api_key or not layout_id:
        raise RuntimeError("CHART_IMG_API_KEY / CHART_IMG_LAYOUT_ID kosong")
    body = {
        "symbol": tv_symbol(cand["pair"]),
        "interval": INTERVAL_OF[cand["timeframe"]],
        "width": int(os.environ.get("CHART_IMG_WIDTH", "800")),
        "height": int(os.environ.get("CHART_IMG_HEIGHT", "600")),
    }
    resp = requests.post(LAYOUT_URL.format(layout_id=layout_id), json=body,
                         headers={"x-api-key": api_key, "content-type": "application/json"},
                         timeout=timeout)
    if resp.status_code != 200 or not resp.headers.get("content-type", "").startswith("image/"):
        raise RuntimeError(f"chart-img layout {resp.status_code}: {resp.text[:300]}")
    return resp.content
