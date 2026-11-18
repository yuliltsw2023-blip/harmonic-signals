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


def send(text: str) -> None:
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    chat = os.environ["GOLDNEWS_CHAT_ID"]
    r = requests.post(f"https://api.telegram.org/bot{token}/sendMessage", json={
        "chat_id": chat, "text": text, "parse_mode": "HTML",
        "disable_web_page_preview": True}, timeout=30)
    if not r.ok:
        raise RuntimeError(f"Telegram {r.status_code}: {r.text[:200]}")
