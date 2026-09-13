"""Yahoo Finance chart endpoint (tanpa API key) — dipakai untuk saham US &
IDX karena Twelve Data free tier tidak punya IDX dan tidak kasih volume forex.

Output format sama dengan TwelveDataClient.get_candles(), plus "volume".
Endpoint tidak resmi (query1.finance.yahoo.com/v8/finance/chart) — kalau
suatu hari diblokir, scan saham error tapi scan forex/crypto tidak terganggu.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import requests


class YahooError(RuntimeError):
    pass


class YahooClient:
    BASE_URL = "https://query1.finance.yahoo.com/v8/finance/chart"
    INTERVAL = {"1h": "1h", "1day": "1d", "1week": "1wk"}
    # range dipilih supaya jumlah bar >= outputsize default (200)
    RANGE = {"1h": "60d", "1day": "1y", "1week": "5y"}
    MIN_INTERVAL_SEC = 1.0
    HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/140 Safari/537.36",
        "Accept": "application/json",
    }

    def __init__(self, min_interval: float | None = None):
        self.min_interval = self.MIN_INTERVAL_SEC if min_interval is None else min_interval
        self._last = 0.0
        self.request_count = 0

    def _rate_limit(self) -> None:
        elapsed = time.time() - self._last
        if self._last and elapsed < self.min_interval:
            time.sleep(self.min_interval - elapsed)
        self._last = time.time()

    def get_candles(self, symbol: str, interval: str, outputsize: int = 200, retries: int = 2) -> list[dict]:
        if interval not in self.INTERVAL:
            raise YahooError(f"interval {interval} tidak didukung Yahoo (pakai 1h/1day/1week)")
        last_err: Exception | None = None
        for attempt in range(retries + 1):
            self._rate_limit()
            self.request_count += 1
            try:
                resp = requests.get(
                    f"{self.BASE_URL}/{symbol}",
                    params={"interval": self.INTERVAL[interval], "range": self.RANGE[interval],
                            "includePrePost": "false"},
                    headers=self.HEADERS,
                    timeout=20,
                )
                if resp.status_code == 429 and attempt < retries:
                    time.sleep(15)
                    last_err = YahooError("rate limited")
                    continue
                data = resp.json()
            except (requests.RequestException, ValueError) as e:
                last_err = e
                continue
            return parse_chart(data, interval)[-outputsize:]
        raise YahooError(f"gagal fetch {symbol} {interval}: {last_err}")


def parse_chart(data: dict, interval: str) -> list[dict]:
    """Parse JSON /v8/finance/chart → candle list oldest-first. Bar dengan
    OHLC null (hari libur bursa / bar belum lengkap) dibuang."""
    chart = data.get("chart") or {}
    if chart.get("error"):
        raise YahooError(f"Yahoo error: {chart['error']}")
    results = chart.get("result") or []
    if not results:
        raise YahooError("Yahoo: result kosong")
    r = results[0]
    ts = r.get("timestamp") or []
    q = (r.get("indicators", {}).get("quote") or [{}])[0]
    tz_name = r.get("meta", {}).get("exchangeTimezoneName") or "UTC"
    try:
        tz = ZoneInfo(tz_name)
    except Exception:  # noqa: BLE001
        tz = timezone.utc
    out: list[dict] = []
    for i, t in enumerate(ts):
        o, h, l, c = q.get("open", [None])[i], q.get("high", [None])[i], q.get("low", [None])[i], q.get("close", [None])[i]
        if o is None or h is None or l is None or c is None:
            continue
        v = (q.get("volume") or [None])[i]
        dt = datetime.fromtimestamp(t, tz=tz)
        if interval in ("1day", "1week"):
            stamp = dt.strftime("%Y-%m-%d")
        else:
            stamp = dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        out.append({"datetime": stamp, "open": float(o), "high": float(h), "low": float(l),
                    "close": float(c), "volume": float(v or 0.0)})
    return out
