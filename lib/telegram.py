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


def format_caption(cand: dict, grade: dict) -> str:
    """Caption foto (limit Telegram 1024 char): ringkasan level saja."""
    d = price_decimals(cand["pair"])
    f = lambda x: f"{x:.{d}f}"
    prz = cand["prz"]
    dirn = "BULL" if cand["direction"] == "bull" else "BEAR"
    return "\n".join([
        f"<b>{html.escape(cand['pair'])} — {html.escape(cand['pattern'])} {dirn} on {cand['timeframe']}</b>",
        f"Grade <b>{grade['grade']}</b> · {html.escape(grade.get('entry_model', '-'))} · HTF {html.escape(cand.get('htf_alignment', '-'))}",
        f"PRZ {f(prz['low'])} – {f(prz['high'])} ({prz['confluence']} confluence)",
        f"SL {f(cand['sl'])}",
        f"TP1 {f(cand['tps']['tp1'])} · TP2 {f(cand['tps']['tp2'])} · TP3 {f(cand['tps']['tp3'])}",
        f"R:R ke TP2 {cand['rr']['tp2']:.1f}:1",
        "<i>detail di pesan berikutnya</i>",
    ])


def _creds() -> tuple[str, str]:
    return os.environ["TELEGRAM_BOT_TOKEN"].strip(), os.environ["TELEGRAM_CHAT_ID"].strip()


def send_photo(png: bytes, caption: str, parse_mode: str = "HTML") -> dict:
    token, chat_id = _creds()
    resp = requests.post(
        f"https://api.telegram.org/bot{token}/sendPhoto",
        data={"chat_id": chat_id, "caption": caption, "parse_mode": parse_mode},
        files={"photo": ("signal.png", png, "image/png")},
        timeout=30,
    )
    data = resp.json()
    if not data.get("ok"):
        raise RuntimeError(f"Telegram sendPhoto error: {data}")
    return data


def send_message(text: str, parse_mode: str = "HTML") -> dict:
    token, chat_id = _creds()
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


def send_signal(cand: dict, grade: dict, candles: list[dict] | None = None) -> dict:
    """Foto chart (kalau candles tersedia & render sukses) lalu pesan detail."""
    if candles:
        try:
            from lib.chart import render_signal_chart
            send_photo(render_signal_chart(cand, candles, grade), format_caption(cand, grade))
        except Exception as e:  # noqa: BLE001 — chart gagal jangan sampai batalin sinyal
            print(f"[warn] chart gagal ({type(e).__name__}: {e}), kirim teks saja")
    return send_message(format_signal(cand, grade))
