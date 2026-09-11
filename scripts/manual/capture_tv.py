#!/usr/bin/env python3
"""Screenshot TradingView Desktop lewat Chrome DevTools Protocol langsung
(port --remote-debugging-port=9222), dengan timeout sendiri.

python scripts/manual/capture_tv.py out.png [--port 9222] [--timeout 30]
"""

import argparse
import base64
import json

import requests
import websocket  # websocket-client

ap = argparse.ArgumentParser()
ap.add_argument("out")
ap.add_argument("--port", type=int, default=9222)
ap.add_argument("--timeout", type=float, default=30)
args = ap.parse_args()

targets = requests.get(f"http://127.0.0.1:{args.port}/json", timeout=5).json()
page = next(t for t in targets if t.get("type") == "page" and "tradingview.com/chart" in t.get("url", ""))
print("target:", page["url"])

# Tab chart harus visible, kalau tidak Chromium tidak render frame dan
# captureScreenshot menggantung selamanya (penyebab hang MCP 30 menit).
r = requests.get(f"http://127.0.0.1:{args.port}/json/activate/{page['id']}", timeout=5)
print("activate:", r.status_code, r.text.strip())
ws = websocket.create_connection(page["webSocketDebuggerUrl"], timeout=args.timeout, suppress_origin=True)
ws.send(json.dumps({"id": 0, "method": "Page.bringToFront"}))
import time; time.sleep(3)
ws.send(json.dumps({"id": 1, "method": "Page.captureScreenshot", "params": {"format": "png", "captureBeyondViewport": False}}))
while True:
    msg = json.loads(ws.recv())
    if msg.get("id") == 1:
        break
ws.close()
if "error" in msg:
    raise SystemExit(f"CDP error: {msg['error']}")
data = base64.b64decode(msg["result"]["data"])
open(args.out, "wb").write(data)
print("saved", args.out, len(data), "bytes")
