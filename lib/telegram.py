"""Telegram Bot API delivery — format MDB-style dari skill."""

from __future__ import annotations

import html
import os

import requests

from config.pairs import price_decimals

DISCLAIMER = ("⚠️ Analisis edukatif. Bukan sinyal buy/sell. Semua keputusan trading "
              "dan konsekuensinya tanggung jawab pribadi.")
DISCLAIMER_SHORT = "⚠️ analisis edukatif, bukan sinyal buy/sell"


def verbose() -> bool:
    """SIGNAL_VERBOSE=true → format panjang lama (struktur, rasio, reasoning).
    Default: ringkas — arah, grade, PRZ/zona, SL, TP1, TP2 dalam satu pesan."""
    return os.environ.get("SIGNAL_VERBOSE", "false").strip().lower() == "true"


STAGE_EMOJI = {"approaching": "👀", "in_va": "🎯", "reacted": "✅"}


def side_label(cand: dict) -> str:
    """bull → LONG (buy di PRZ), bear → SHORT (sell di PRZ)."""
    return "LONG 🟢 (buy di PRZ)" if cand["direction"] == "bull" else "SHORT 🔴 (sell di PRZ)"


def scan_stamp(cand: dict) -> str:
    """Jam scan sebenarnya (bukan jam candle) — supaya user tahu seberapa
    basi harganya saat pesan dibaca."""
    return cand.get("scan_datetime") or (cand.get("current_datetime", "")[:16] + " UTC")


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
        f"Arah: <b>{side_label(cand)}</b>",
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


def format_compact(cand: dict, grade: dict) -> str:
    """Pesan ringkas harmonic (muat sebagai caption foto, <1024 char)."""
    d = price_decimals(cand["pair"])
    f = lambda x: f"{x:.{d}f}"
    prz = cand["prz"]
    esc = html.escape
    dirn = "BULL" if cand["direction"] == "bull" else "BEAR"
    up = cand["direction"] == "bull"
    side = "LONG 🟢" if up else "SHORT 🔴"
    order = f"Limit {'BUY' if up else 'SELL'} <b>{f(cand['entry'])}</b> (mid PRZ)"
    stage = cand.get("stage", "in_prz")
    px = f(cand["current_price"])
    if stage == "in_prz":
        head = f"✅ <b>MASUK ZONA</b> · {side} · Grade <b>{grade['grade']}</b>"
        act = [f"Harga <b>{px}</b> sudah di PRZ → limit lo harusnya aktif. Belum pasang? {order.replace('Limit', 'entry sekarang / limit')}"]
    else:
        head = f"🕒 <b>SIAPKAN ORDER</b> · {side} · Grade <b>{grade['grade']}</b>"
        act = [f"Pasang: {order}",
               f"Harga <b>{px}</b> · masih {cand.get('prz_distance_pct', 0):.2%} dari zona, jangan entry market"]
    lines = [
        f"<b>{esc(cand['pair'])} · {esc(cand['pattern'])} {dirn} · {cand['timeframe']}</b>",
        head, *act,
        f"PRZ: <b>{f(prz['low'])} – {f(prz['high'])}</b>",
        f"SL: <b>{f(cand['sl'])}</b>",
        f"TP1: <b>{f(cand['tps']['tp1'])}</b> (R:R {cand['rr']['tp1']:.1f})",
        f"TP2: <b>{f(cand['tps']['tp2'])}</b> (R:R {cand['rr']['tp2']:.1f})",
        f"<i>{DISCLAIMER_SHORT} · scan {scan_stamp(cand)}</i>",
    ]
    return "\n".join(lines)


def format_left_notice(cand: dict) -> str:
    """Pesan teks singkat: harga sudah lewat PRZ menuju TP — jangan kejar."""
    d = price_decimals(cand["pair"])
    f = lambda x: f"{x:.{d}f}"
    esc = html.escape
    prz = cand["prz"]
    dirn = "BULL" if cand["direction"] == "bull" else "BEAR"
    return "\n".join([
        f"⚠️ <b>{esc(cand['pair'])} · {esc(cand['pattern'])} {dirn} · {cand['timeframe']}</b> — JANGAN KEJAR",
        f"Harga <b>{f(cand['current_price'])}</b> sudah lewat PRZ {f(prz['low'])} – {f(prz['high'])} "
        f"ke arah TP1 {f(cand['tps']['tp1'])}.",
        f"Kalau limit lo sudah kena: kelola SL <b>{f(cand['sl'])}</b> · TP1 <b>{f(cand['tps']['tp1'])}</b> · "
        f"TP2 <b>{f(cand['tps']['tp2'])}</b>. Kalau belum kena, lewatkan setup ini.",
        f"<i>scan {scan_stamp(cand)}</i>",
    ])


def send_left_notice(cand: dict) -> dict:
    return send_message(format_left_notice(cand))


def format_poc_compact(cand: dict) -> str:
    """Pesan ringkas POC pullback: zona VA, entry POC, SL, TP1, TP2."""
    d = price_decimals(cand["pair"])
    f = lambda x: f"{x:.{d}f}"
    esc = html.escape
    up = cand["direction"] == "bull"
    side = "LONG 🟢 (buy di pullback)" if up else "SHORT 🔴 (sell di pullback)"
    g = cand.get("grade", {}).get("grade", "-")
    emoji = STAGE_EMOJI.get(cand["stage"], "•")
    lines = [
        f"<b>{esc(cand['pair'])} · POC PULLBACK {'BUY' if up else 'SELL'} · {cand['timeframe']}</b>",
        f"Arah: <b>{side}</b> · Grade <b>{g}</b> · {emoji} {esc(cand.get('stage_label', cand['stage']))}",
        f"Pasang: Limit {'BUY' if up else 'SELL'} <b>{f(cand['poc'])}</b> (POC) · harga sekarang {f(cand['current_price'])}",
        f"Zona: <b>{f(min(cand['val'], cand['vah']))} – {f(max(cand['val'], cand['vah']))}</b> (VAL–VAH)",
        f"SL: <b>{f(cand['sl'])}</b>",
        f"TP1: <b>{f(cand['tps']['tp1'])}</b> (R:R {cand['rr']['tp1']:.1f})",
        f"TP2: <b>{f(cand['tps']['tp2'])}</b> (R:R {cand['rr']['tp2']:.1f})",
        f"<i>{DISCLAIMER_SHORT} · scan {scan_stamp(cand)}</i>",
    ]
    return "\n".join(lines)


def format_caption(cand: dict, grade: dict) -> str:
    """Caption foto (limit Telegram 1024 char): ringkasan level saja."""
    d = price_decimals(cand["pair"])
    f = lambda x: f"{x:.{d}f}"
    prz = cand["prz"]
    dirn = "BULL" if cand["direction"] == "bull" else "BEAR"
    return "\n".join([
        f"<b>{html.escape(cand['pair'])} — {html.escape(cand['pattern'])} {dirn} on {cand['timeframe']}</b>",
        f"Arah: <b>{side_label(cand)}</b>",
        f"Grade <b>{grade['grade']}</b> · {html.escape(grade.get('entry_model', '-'))} · HTF {html.escape(cand.get('htf_alignment', '-'))}",
        f"PRZ {f(prz['low'])} – {f(prz['high'])} ({prz['confluence']} confluence)",
        f"SL {f(cand['sl'])}",
        f"TP1 {f(cand['tps']['tp1'])} · TP2 {f(cand['tps']['tp2'])} · TP3 {f(cand['tps']['tp3'])}",
        f"R:R ke TP2 {cand['rr']['tp2']:.1f}:1",
        f"<i>detail di pesan berikutnya · chart: {html.escape(cand.get('chart_source', '-'))}</i>",
    ])


# ---------------------------------------------------------------------------
# POC Pullback (strategi kedua) — teks saja, tanpa chart
# ---------------------------------------------------------------------------

def format_poc_signal(cand: dict) -> str:
    d = price_decimals(cand["pair"])
    f = lambda x: f"{x:.{d}f}"
    esc = html.escape
    g = cand.get("grade", {})
    up = cand["direction"] == "bull"
    side = "LONG 🟢 (buy di pullback)" if up else "SHORT 🔴 (sell di pullback)"
    st = cand["structure"]
    leg = cand["leg"]
    prof = cand["profile"]
    prof_src = "volume" if prof["source"] == "volume" else "TPO/time-at-price (tanpa volume)"
    emoji = STAGE_EMOJI.get(cand["stage"], "•")
    lines = [
        f"<b>{esc(cand['pair'])} — POC PULLBACK {'BUY' if up else 'SELL'} on {cand['timeframe']}</b>",
        f"Arah: <b>{side}</b>",
        f"{emoji} Stage: <b>{esc(cand['stage_label'])}</b>",
        f"Grade: <b>{g.get('grade', '-')}</b>  ·  HTF {esc(cand.get('htf_timeframe', '-'))}: {esc(cand.get('htf_alignment', 'neutral'))}",
        "",
        "<b>Struktur</b>",
        f"  Swing H: {f(st['prev_h'])} → {f(st['last_h'])}  ({'HH' if st['last_h'] > st['prev_h'] else 'LH'})",
        f"  Swing L: {f(st['prev_l'])} → {f(st['last_l'])}  ({'HL' if st['last_l'] > st['prev_l'] else 'LL'})",
        f"  Bias: {'BULLISH' if up else 'BEARISH'}",
        f"  Leg impulsif: {f(leg['start_price'])} ({leg['start_datetime'][:10]}) → {f(leg['end_price'])} ({leg['end_datetime'][:10]}), {leg['bars']} candle",
        "",
        f"<b>Volume Profile</b> (fixed range, {prof['bins']} bin, {esc(prof_src)})",
        f"  VAH: {f(cand['vah'])}",
        f"  POC: <b>{f(cand['poc'])}</b>  (kedalaman {cand['depth']:.2f} = {esc(cand['depth_label'])})",
        f"  VAL: {f(cand['val'])}",
        "",
        f"<b>Harga</b> {f(cand['current_price'])} · jarak ke tepi VA {cand['distance_pct']:.2%}",
        "  Reaksi: " + (esc(", ".join(cand["reactions"])) if cand["reactions"] else "belum ada — tunggu candle close di dalam VA"),
        "",
        "<b>Rencana</b> (entry limit di POC)",
        f"  SL konservatif {f(cand['sl'])} ({'di bawah swing low' if up else 'di atas swing high'} + buffer)",
        f"  SL agresif {f(cand['sl_aggressive'])} ({'di bawah VAL' if up else 'di atas VAH'}, hanya kalau reaksi jelas)",
        f"  TP1 {f(cand['tps']['tp1'])} (swing {'high' if up else 'low'} leg) — R:R {cand['rr']['tp1']:.1f}:1 (SL swing) · {cand['rr_aggressive']['tp1']:.1f}:1 (SL VA)",
        f"  TP2 {f(cand['tps']['tp2'])} (1.272 ext) — R:R {cand['rr']['tp2']:.1f}:1 · {cand['rr_aggressive']['tp2']:.1f}:1",
        f"  TP3 {f(cand['tps']['tp3'])} (1.618 ext) — R:R {cand['rr']['tp3']:.1f}:1 · {cand['rr_aggressive']['tp3']:.1f}:1",
        "",
        "<b>Reasoning</b>",
    ]
    for r in g.get("reasoning", []):
        lines.append(f"  • {esc(r)}")
    lines += [
        "",
        f"<b>Invalidation</b>: close {'di bawah' if up else 'di atas'} {f(leg['start_price'])} (struktur patah). "
        f"Melemah kalau close {'di bawah VAL' if up else 'di atas VAH'}.",
        "Cek manual: news ≤2 jam / earnings / ex-date, dan candle reaksi sebelum klik.",
        "",
        f"<i>{esc(DISCLAIMER)}</i>",
        f"<i>screener: poc-pullback (rule) · harga {f(cand['current_price'])} @ {cand['current_datetime']}</i>",
    ]
    return "\n".join(lines)


def send_poc_signal(cand: dict, candles: list[dict] | None = None) -> dict:
    """Satu pesan: foto chart POC (kalau candles ada) dengan caption ringkas.
    SIGNAL_VERBOSE=true → tambah pesan teks panjang setelahnya."""
    png = None
    if candles:
        try:
            from lib.chart_poc import render_poc_chart
            png = render_poc_chart(cand, candles)
            cand["chart_source"] = "matplotlib"
        except Exception as e:  # noqa: BLE001
            print(f"[warn] chart POC gagal ({type(e).__name__}: {e}), kirim teks saja")
    text = format_poc_compact(cand)
    result, sent = None, False
    if png:
        try:
            result = send_photo(png, text); sent = True
        except Exception as e:  # noqa: BLE001
            print(f"[warn] sendPhoto POC gagal ({type(e).__name__}: {e}), kirim teks saja")
    if not sent:
        result = send_message(text)
    if verbose():
        result = send_message(format_poc_signal(cand))
    return result


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
    png = None
    if os.environ.get("CHART_IMG_API_KEY", "").strip():
        if os.environ.get("CHART_IMG_LAYOUT_ID", "").strip():
            try:
                from lib.chart_img import render_layout_chart
                png = render_layout_chart(cand)
                cand["chart_source"] = "TradingView layout (chart-img)"
            except Exception as e:  # noqa: BLE001
                print(f"[warn] chart-img layout gagal ({type(e).__name__}: {e})")
        if png is None:
            try:
                from lib.chart_img import render_chart_img
                png = render_chart_img(cand, grade)
                cand["chart_source"] = "chart-img (TradingView)"
            except Exception as e:  # noqa: BLE001
                print(f"[warn] chart-img gagal ({type(e).__name__}: {e}), fallback matplotlib")
    if png is None and candles:
        try:
            from lib.chart import render_signal_chart
            png = render_signal_chart(cand, candles, grade)
            cand["chart_source"] = "matplotlib"
        except Exception as e:  # noqa: BLE001 — chart gagal jangan sampai batalin sinyal
            print(f"[warn] chart gagal ({type(e).__name__}: {e}), kirim teks saja")
    text = format_compact(cand, grade)
    result, sent = None, False
    if png:
        try:
            result = send_photo(png, text); sent = True
        except Exception as e:  # noqa: BLE001
            print(f"[warn] sendPhoto gagal ({type(e).__name__}: {e}), kirim teks saja")
    if not sent:
        result = send_message(text)
    if verbose():
        result = send_message(format_signal(cand, grade))
    return result
