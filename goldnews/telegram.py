"""Format & kirim briefing ke channel Telegram Gold News (HTML parse mode)."""

from __future__ import annotations

import html
import os
from datetime import datetime

import requests

from .sessions import WIB

BIAS_ICON = {"bullish": "🟢", "bearish": "🔴", "sideways": "⚪", "netral": "⚪"}
DAYS = ["Sen", "Sel", "Rab", "Kam", "Jum", "Sab", "Min"]


def _t(ts: int, fmt: str = "%H:%M") -> str:
    return datetime.fromtimestamp(ts, WIB).strftime(fmt)


def _stamp(ts: int) -> str:
    d = datetime.fromtimestamp(ts, WIB)
    return f"{DAYS[d.weekday()]} {d:%d %b %H:%M} WIB"


def format_briefing(report: dict, link: str = "") -> str:
    e = html.escape
    a = report["analysis"]
    p = report["price"]
    b = a["bias"]
    out = [f"🟡 <b>GOLD BRIEFING · {e(report['slot_label'])}</b>",
           f"{_stamp(report['t'])} · XAU/USD <b>{p['last']:,.2f}</b>",
           "", f"<b>{e(a['headline'])}</b>", ""]

    done = [s for s in report["sessions"] if s["complete"] or s is report["sessions"][-1]]
    for s in done[-3:]:
        run = "" if s["complete"] else " (berjalan)"
        out.append(f"📊 {s['name']}{run}: {BIAS_ICON[s['label']]} <b>{s['label'].upper()}</b> "
                   f"{s['change']:+.1f} · range {s['range']:.1f} ({s['range_vs_adr']:.0%} ADR)")
    if report.get("prev_eval"):
        pe = report["prev_eval"]
        out.append(f"🧾 Outlook {pe['session_name']} sebelumnya: {pe['predicted']} → {pe['actual']} "
                   f"{'✅' if pe['hit'] else '❌'}")
    out += ["", f"🎯 <b>Outlook {e(report['target_label'])}: {BIAS_ICON[b['direction']]} "
                f"{b['direction'].upper()}</b> (keyakinan {b['confidence']})",
            f"<i>{e(b['reason'])}</i>"]

    if report["key_news"]:
        out += ["", "📰 <b>Berita kunci</b>"]
        for n in report["key_news"][:5]:
            out.append(f"{BIAS_ICON[n['effect']]} {_t(n['t'])} {e(n['title'][:120])}\n   ↳ {e(n['why'])}")
    if a["event_risks"]:
        out += ["", "📅 <b>Event berikutnya</b>"]
        for ev in a["event_risks"][:4]:
            out.append(f"• {e(ev['time_wib'])} {e(ev['event'])} — {e(ev['scenario'])}")
    lv = a["levels"]
    if lv["support"] or lv["resistance"]:
        out += ["", "🧭 S " + " / ".join(f"{x:,.0f}" for x in lv["support"][:3])
                + "  ·  R " + " / ".join(f"{x:,.0f}" for x in lv["resistance"][:3])]
    if a["scenarios"]:
        out += ["", "➡️ <b>Skenario</b>"]
        for sc in a["scenarios"][:3]:
            out.append(f"• {e(sc['if_'])} → {e(sc['then'])}")
    if link:
        out += ["", f'🔗 <a href="{e(link)}">Analisa lengkap + chart berita</a>']
    out.append("<i>⚠️ konteks pasar, bukan sinyal entry</i>")
    text = "\n".join(out)
    if len(text) > 4000:  # batas Telegram 4096
        text = text[:3990].rsplit("\n", 1)[0] + "\n…"
    return text


RESULT = {"tp2": "✅ TP2", "tp1": "✅ TP1", "sl": "❌ SL", "expired": "⌛ ditutup (kedaluwarsa)",
          "not_filled": "⏹ tidak terisi"}


def format_sessions(sessions: list[dict], src: str) -> str:
    """Caption foto kotak sesi (3 sesi terakhir)."""
    out = ["📊 <b>Hasil sesi XAU/USD</b> (kotak = high–low sesi)"]
    for s in sessions[-3:]:
        run = " (berjalan)" if not s["complete"] else ""
        out.append(f"{BIAS_ICON[s['label']]} <b>{s['name']}</b>{run} {s['hours_wib']}: <b>{s['label'].upper()}</b> "
                   f"{s['change']:+.1f} · O {s['open']:,.1f} → C {s['close']:,.1f} · "
                   f"range {s['range']:.1f} ({s['range_vs_adr']:.0%} ADR)")
    out.append("<i>Hijau = Bullish · Merah = Bearish · Abu = Sideways · "
               f"📷 {'TradingView' if src == 'tradingview' else 'chart cadangan'}</i>")
    return "\n".join(out)[:1024]


def _cut(text: str, n: int) -> str:
    text = (text or "").strip()
    return text if len(text) <= n else text[:n].rsplit(" ", 1)[0].rstrip(",.;:") + "…"


def format_plan(p: dict, trend: dict | None = None, prev_meta: dict | None = None) -> str:
    """Caption foto rencana trading (maks 1024 karakter)."""
    e = html.escape
    name = "INTRADAY" if p["style"] == "intraday" else "SCALPING"
    out = []
    if trend:
        out.append("🧭 <b>Tren</b> H4 {} · H1 {} · M15 {} · M5 {}".format(
            *(BIAS_ICON[trend[k]] for k in ("h4", "h1", "m15", "m5"))))
        out.append(f"<i>{e(trend['summary'][:220])}</i>")
        if prev_meta:
            res = []
            for pp, ev in zip(prev_meta["plans"], prev_meta["plan_evals"]):
                if not ev:
                    continue
                r = "" if ev["result"] == "not_filled" else f" ({ev['r']:+.1f}R)"
                res.append(f"{pp['style']} {pp['action'].upper()} → {RESULT.get(ev['result'], ev['result'])}{r}")
            if res:
                out.append("🧾 Rencana sebelumnya: " + "; ".join(res))
        out.append("")
    act = p["action"]
    if act == "no_trade":
        out.append(f"⏸ <b>{name} ({p['tf']}) · TIDAK ADA SETUP</b>")
        out.append(e(p["reason"][:300]))
        if p.get("rejected"):
            out.append(f"<i>(usulan ditolak: {e(p['rejected'])})</i>")
    else:
        waiting = act.startswith("wait_")
        side = "BUY" if act.endswith("buy") else "SELL"
        icon = "🟢" if side == "BUY" else "🔴"
        head = f"⏳ <b>{name} ({p['tf']}) · TUNGGU {side}</b> — belum entry" if waiting else             f"{icon} <b>{name} ({p['tf']}) · {side} {p['order'].upper()}</b> — 4 langkah lengkap"
        out.append(head)
        ck = p.get("check") or {}
        mark = lambda k: "✅" if ck.get(k) else "⏳"
        st = p.get("steps") or {}
        out.append(f"{mark('liquidity')} Liquidity: {e(_cut(st.get('liquidity', ''), 110))}")
        out.append(f"{mark('structure')} Structure: {e(_cut(st.get('structure', ''), 110))}")
        out.append(f"{mark('poi')} POI {e(p.get('poi_label', '')[:30])} {p.get('poi_lo', 0):,.1f}–{p.get('poi_hi', 0):,.1f}: "
                   f"{e(_cut(st.get('poi', ''), 90))}")
        out.append(f"{mark('confirmation')} Entry: {e(_cut(st.get('entry', ''), 110))}")
        lv = (f"Entry {p['entry']:,.2f} · SL {p['sl']:,.2f} · TP1 {p['tp1']:,.2f}"
              + (f" ({p['rr1']:.1f}R)" if p.get("rr1") else "") + f" · TP2 {p['tp2']:,.2f}"
              + (f" ({p['rr2']:.1f}R)" if p.get("rr2") else ""))
        out.append(("<i>Kalau terkonfirmasi:</i> " + lv) if waiting else f"<b>{lv}</b>")
        if waiting and p.get("trigger"):
            out.append(f"🔔 Tunggu: {e(_cut(p['trigger'], 180))}")
        if p.get("gated"):
            out.append(f"<i>({e(p['gated'][:120])})</i>")
        out.append(f"❗ Batal jika: {e(_cut(p['invalidation'], 120))}")
    out.append(f"<i>📷 {'TradingView' if p.get('chart') == 'tradingview' else 'chart cadangan'} · bukan sinyal pasti</i>")
    text = "\n".join(out)
    if len(text) > 1024 and trend:          # buang ringkasan tren dulu
        out.pop(1)
        text = "\n".join(out)
    if len(text) > 1024:                     # potong per baris (tiap baris tag-nya tertutup)
        text = text[:1010].rsplit("\n", 1)[0] + "\n…"
    return text


def send_photo(path: str, caption: str) -> None:
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    chat = os.environ["GOLDNEWS_CHAT_ID"]
    with open(path, "rb") as f:
        r = requests.post(f"https://api.telegram.org/bot{token}/sendPhoto",
                          data={"chat_id": chat, "caption": caption, "parse_mode": "HTML"},
                          files={"photo": ("chart.png", f, "image/png")}, timeout=60)
    if not r.ok:
        raise RuntimeError(f"Telegram foto {r.status_code}: {r.text[:200]} | {_diagnose(token, chat)}")


def send_all(messages: list[dict]) -> None:
    for m in messages:
        if m["type"] == "text":
            send(m["text"])
        elif m["type"] == "photo":
            send_photo(m["path"], m["caption"])


def send(text: str) -> None:
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    chat = os.environ["GOLDNEWS_CHAT_ID"]
    r = requests.post(f"https://api.telegram.org/bot{token}/sendMessage", json={
        "chat_id": chat, "text": text, "parse_mode": "HTML",
        "disable_web_page_preview": True}, timeout=30)
    if not r.ok:
        raise RuntimeError(f"Telegram {r.status_code}: {r.text[:200]} | {_diagnose(token, chat)}")


def _diagnose(token: str, chat: str) -> str:
    """Info aman untuk log: bot mana yang dipakai & bentuk chat id (tanpa membuka secret)."""
    try:
        me = requests.get(f"https://api.telegram.org/bot{token}/getMe", timeout=15).json()
        bot = "@" + me["result"]["username"] if me.get("ok") else f"token tidak valid ({me.get('description')})"
    except Exception as e:  # noqa: BLE001
        bot = f"getMe gagal ({e.__class__.__name__})"
    c = chat.strip()
    shape = (f"chat_id panjang {len(chat)} karakter"
             f"{' (ada spasi/enter!)' if c != chat else ''}, awalan '{c[:4]}', "
             f"{'format -100… benar' if c.startswith('-100') and c[1:].isdigit() else 'format BUKAN -100…'}")
    return f"bot={bot}; {shape}"
