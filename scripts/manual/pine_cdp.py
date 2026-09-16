#!/usr/bin/env python3
"""Utilitas Pine Editor lewat CDP langsung (tanpa lewat konteks LLM).

python scripts/manual/pine_cdp.py header                 # nama script yang terbuka di editor
python scripts/manual/pine_cdp.py set path/to/file.pine   # isi editor dari file lokal (Monaco setValue)
python scripts/manual/pine_cdp.py get out.pine            # simpan isi editor ke file
"""

import json
import sys

import requests
import websocket

PORT = 9222


def _ws():
    targets = requests.get(f"http://127.0.0.1:{PORT}/json", timeout=5).json()
    page = next(t for t in targets if t.get("type") == "page" and "tradingview.com/chart" in t.get("url", ""))
    return websocket.create_connection(page["webSocketDebuggerUrl"], timeout=30, suppress_origin=True)


def evaluate(expr: str):
    ws = _ws()
    ws.send(json.dumps({"id": 1, "method": "Runtime.evaluate",
                        "params": {"expression": expr, "returnByValue": True, "awaitPromise": True}}))
    while True:
        m = json.loads(ws.recv())
        if m.get("id") == 1:
            ws.close()
            r = m.get("result", {})
            if "exceptionDetails" in r:
                raise SystemExit("JS error: " + json.dumps(r["exceptionDetails"])[:500])
            return r.get("result", {}).get("value")


HEADER_JS = """(() => {
  const h = document.querySelector('[class*="nameButton"], [data-name="script-name"]');
  return h ? h.textContent.trim() : null;
})()"""

MODEL_JS = """(() => {
  const models = (window.monaco && monaco.editor && monaco.editor.getModels()) || [];
  return models.map(m => ({uri: m.uri.toString(), lines: m.getLineCount(), lang: m.getLanguageId && m.getLanguageId()}));
})()"""


def main():
    cmd = sys.argv[1]
    if cmd == "header":
        print(evaluate(HEADER_JS))
    elif cmd == "models":
        print(json.dumps(evaluate(MODEL_JS), indent=1))
    elif cmd == "get":
        src = evaluate("(() => { const m = monaco.editor.getModels().find(m => m.getLineCount() > 5); return m ? m.getValue() : null; })()")
        open(sys.argv[2], "w", encoding="utf-8").write(src or "")
        print("saved", len(src or ""), "chars")
    elif cmd == "set":
        src = open(sys.argv[2], encoding="utf-8").read()
        expr = ("(() => { const models = monaco.editor.getModels().filter(m => m.getLanguageId() !== 'json'); "
                "const m = models.sort((a,b) => b.getLineCount() - a.getLineCount())[0]; if (!m) return 'no model'; "
                f"m.setValue({json.dumps(src)}); return 'set ' + m.getLineCount() + ' lines'; }})()")
        print(evaluate(expr))
    else:
        raise SystemExit("cmd: header | models | get <out> | set <file>")


if __name__ == "__main__":
    main()
