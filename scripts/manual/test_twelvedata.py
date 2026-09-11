#!/usr/bin/env python3
"""Fase 1 check: fetch 1 pair, pastikan format & rate limit OK.

python scripts/manual/test_twelvedata.py [PAIR] [INTERVAL]
"""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _bootstrap_manual  # noqa: F401,E402

from lib.twelvedata import TwelveDataClient  # noqa: E402

pair = sys.argv[1] if len(sys.argv) > 1 else "EUR/USD"
interval = sys.argv[2] if len(sys.argv) > 2 else "4h"

tdc = TwelveDataClient(api_key=os.environ["TWELVEDATA_API_KEY"])
t0 = time.time()
candles = tdc.get_candles(pair, interval, outputsize=50)
t1 = time.time()
print(f"{pair} {interval}: {len(candles)} candle dalam {t1 - t0:.1f}s")
print("first:", candles[0])
print("last :", candles[-1])

# request kedua harus tertahan ≥8 detik oleh rate limiter
candles2 = tdc.get_candles(pair, interval, outputsize=5)
t2 = time.time()
print(f"request ke-2 selesai setelah {t2 - t1:.1f}s (harus ≥ 8s) — {len(candles2)} candle")
