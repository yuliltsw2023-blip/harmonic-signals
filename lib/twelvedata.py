"""Twelve Data client (raw HTTP via requests) dengan rate limit free tier."""

import time
from typing import Literal

import requests

Interval = Literal["15min", "30min", "1h", "4h", "1day", "1week"]


class TwelveDataError(RuntimeError):
    pass


class TwelveDataClient:
    BASE_URL = "https://api.twelvedata.com"
    # Free tier: 8 req/menit. 8 detik antar request = 7.5 req/menit, aman.
    MIN_INTERVAL_SEC = 8.0

    def __init__(self, api_key: str, min_interval: float | None = None):
        if not api_key:
            raise TwelveDataError("TWELVEDATA_API_KEY kosong")
        self.api_key = api_key
        self.min_interval = self.MIN_INTERVAL_SEC if min_interval is None else min_interval
        self._last_request_time = 0.0
        self.request_count = 0

    def _rate_limit(self) -> None:
        elapsed = time.time() - self._last_request_time
        if self._last_request_time and elapsed < self.min_interval:
            time.sleep(self.min_interval - elapsed)
        self._last_request_time = time.time()

    def get_candles(
        self,
        symbol: str,          # "EUR/USD" (SLASH, bukan underscore)
        interval: Interval,
        outputsize: int = 200,
        retries: int = 2,
    ) -> list[dict]:
        """Candle list, oldest first:
        [{"datetime": ISO, "open", "high", "low", "close"}, ...]

        Free tier forex tidak return volume — kita memang tidak butuh.
        """
        last_err: Exception | None = None
        for attempt in range(retries + 1):
            self._rate_limit()
            self.request_count += 1
            try:
                resp = requests.get(
                    f"{self.BASE_URL}/time_series",
                    params={
                        "symbol": symbol,
                        "interval": interval,
                        "outputsize": outputsize,
                        "apikey": self.api_key,
                        "order": "ASC",
                        "timezone": "UTC",
                    },
                    timeout=15,
                )
                resp.raise_for_status()
                data = resp.json()
            except (requests.RequestException, ValueError) as e:
                last_err = e
                continue

            if "values" not in data:
                code = data.get("code")
                msg = data.get("message", data)
                # 429 = rate limit ke-hit; tunggu lalu retry.
                if code == 429 and attempt < retries:
                    time.sleep(60)
                    last_err = TwelveDataError(f"rate limited: {msg}")
                    continue
                raise TwelveDataError(f"Twelve Data error ({code}): {msg}")

            return [
                {
                    "datetime": c["datetime"],
                    "open": float(c["open"]),
                    "high": float(c["high"]),
                    "low": float(c["low"]),
                    "close": float(c["close"]),
                }
                for c in data["values"]
            ]

        raise TwelveDataError(f"gagal fetch {symbol} {interval}: {last_err}")
