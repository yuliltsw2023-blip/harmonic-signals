"""Telegram Bot API delivery — format MDB-style dari skill."""

from __future__ import annotations

import html
import os

import requests

from config.pairs import price_decimals

DISCLAIMER = ("⚠️ Analisis edukatif. Bukan sinyal buy/sell. Semua keputusan trading "
              "dan konsekuensinya tanggung jawab pribadi.")


def format_signal(cand: dict, grade: dict) -> str:
    d = price_decimals(cand["pair"])
    f = lambda x: f"{x:.{d}f}"
    p = cand["points"]
    prz = cand["prz"]
    dirn = "BULL" if cand["direction"] == "bull" else "BEAR"
    status = "projected" if cand["d_projected"] else "completed"
    esc = html.escape

    lines = [
        f"<b>{esc(cand['pair'])} — {esc(cand['pattern'])} {dirn} on {cand['timeframe']}</b>",
        f"Grade: <b>{grade['grade']}</b>  ·  D {status}  ·  entry model: {esc(grade.get('entry_model', '-'))}",
        "",
        "<b>Structure</b>",
        f"  X: {f(p['X']['price'])} ({p['X']['datetime'][:10]})",
        f"  A: {f(p['A']['price'])} ({p['A']['datetime'][:10]})",
        f"  B: {f(p['B']['price'])} ({p['B']['datetime'][:10]})",
        f"  C: {f(p['C']['price'])} ({p['C']['datetime'][:10]})",
    ]
    if p["D"]:
        lines.append(f"  D: {f(p['D']['price'])} ({p['D']['datetime'][:10]})")
    else:
        lines.append(f"  D projected: {f(prz['low'])} – {f(prz['high'])}")

    lines += ["", "<b>Ratios</b>"]
    for k, v in cand["ratios"].items():
        if k in cand["deviations"]:
            lines.append(f"  {k} = {v:.3f} (dev {cand['deviations'][k]:.1%})")

    lines += ["", f"<b>PRZ</b> {f(prz['low'])} – {f(prz['high'])}  ({prz['confluence']} confluence)"]
    for lv in prz["levels"]:
        lines.append(f"  • {esc(lv['name'])} @ {f(lv['price'])}")

    lines += [
        "",
        f"<b>SL</b> {f(cand['sl'])} (beyond X)",
        "<b>Targets</b>",
        f"  TP1 @ {f(cand['tps']['tp1'])} (0.382 AD) — R:R {cand['rr']['tp1']:.1f}:1",
        f"  TP2 @ {f(cand['tps']['tp2'])} (0.618 AD) — R:R {cand['rr']['tp2']:.1f}:1",
        f"  TP3 @ {f(cand['tps']['tp3'])} (1.0 AD) — R:R {cand['rr']['tp3']:.1f}:1",
        "",
        f"<b>HTF</b> {esc(cand.get('htf_timeframe', '-'))}: {esc(cand.get('htf_alignment', 'neutral'))}",
        "",
        "<b>Reasoning</b>",
    ]
    for r in grade.get("reasoning", []):
        lines.append(f"  • {esc(r)}")
    if grade.get("warnings"):
        lines.append("<b>Warnings</b>")
        for w in grade["warnings"]:
            lines.append(f"  ⚠ {esc(w)}")
    lines += ["", f"<b>Invalidation</b>: {esc(grade.get('invalidation', '-'))}",
              "", f"<i>{esc(DISCLAIMER)}</i>",
              f"<i>grader: {esc(grade.get('source', '?'))} · harga {f(cand['current_price'])} @ {cand['current_datetime']}</i>"]
    return "\n".join(lines)


def send_message(text: str, parse_mode: str = "HTML") -> dict:
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    chat_id = os.environ["TELEGRAM_CHAT_ID"]
    resp = requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={"chat_id": chat_id, "text": text, "parse_mode": parse_mode,
              "disable_web_page_preview": True},
        timeout=15,
    )
    data = resp.json()
    if not data.get("ok"):
        raise RuntimeError(f"Telegram error: {data}")
    return data


def send_signal(cand: dict, grade: dict) -> dict:
    return send_message(format_signal(cand, grade))
