"""Unduh histori candle untuk backtest: semua simbol SCAN_SYMBOLS × interval.
Simpan ke data/history/<SYMBOL>_<interval>.json (oldest first). Free tier:
8 req/menit, outputsize maks 5000. Pakai: python scripts/manual/fetch_history.py [1h,4h,1day]
"""
import json, os, sys, time, requests
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from dotenv import load_dotenv
load_dotenv(".env")
from config.pairs import SCAN_SYMBOLS
key = os.environ["TWELVEDATA_API_KEY"].strip()
intervals = (sys.argv[1] if len(sys.argv) > 1 else "1h,4h,1day").split(",")
size = {"1h": 5000, "4h": 5000, "1day": 3000}
done = 0
for sym in SCAN_SYMBOLS:
    for iv in intervals:
        fn = f"data/history/{sym.replace('/', '')}_{iv}.json"
        if os.path.exists(fn):
            continue
        for attempt in range(3):
            r = requests.get("https://api.twelvedata.com/time_series",
                             params={"symbol": sym, "interval": iv, "outputsize": size.get(iv, 5000),
                                     "apikey": key, "order": "ASC", "timezone": "UTC"}, timeout=60)
            j = r.json()
            if "values" in j:
                json.dump([{"datetime": c["datetime"], "open": float(c["open"]), "high": float(c["high"]),
                            "low": float(c["low"]), "close": float(c["close"])} for c in j["values"]], open(fn, "w"))
                print(fn, len(j["values"]), j["values"][0]["datetime"], "->", j["values"][-1]["datetime"], flush=True)
                break
            print(sym, iv, "ERR", j.get("code"), str(j.get("message"))[:80], flush=True)
            time.sleep(60 if j.get("code") == 429 else 8.5)
        done += 1
        time.sleep(8.5)
print("DONE", done, flush=True)
