"""Analisa Claude: berita + kalender + hasil sesi + makro → outlook sesi berikut.

Output dipaksa JSON lewat structured outputs (output_config.format), jadi
website & Telegram tidak perlu parsing teks bebas.
"""

from __future__ import annotations

import json
import os
from datetime import datetime

import anthropic

from .sessions import WIB

MODEL = os.environ.get("GOLDNEWS_MODEL") or "claude-sonnet-5-5"
EFFORT = os.environ.get("GOLDNEWS_EFFORT") or "medium"

EFFECT = {"type": "string", "enum": ["bullish", "bearish", "netral"]}
FACTOR = {
    "type": "object",
    "additionalProperties": False,
    "required": ["factor", "view", "effect"],
    "properties": {
        "factor": {"type": "string"},
        "view": {"type": "string"},
        "effect": EFFECT,
    },
}
SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["headline", "bias", "session_review", "macro", "micro", "key_news",
                 "event_risks", "levels", "scenarios"],
    "properties": {
        "headline": {"type": "string"},
        "bias": {
            "type": "object",
            "additionalProperties": False,
            "required": ["direction", "confidence", "reason"],
            "properties": {
                "direction": {"type": "string", "enum": ["bullish", "bearish", "sideways"]},
                "confidence": {"type": "string", "enum": ["rendah", "sedang", "tinggi"]},
                "reason": {"type": "string"},
            },
        },
        "session_review": {"type": "string"},
        "macro": {"type": "array", "items": FACTOR},
        "micro": {"type": "array", "items": FACTOR},
        "key_news": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["n", "impact", "effect", "why"],
                "properties": {
                    "n": {"type": "integer"},
                    "impact": {"type": "string", "enum": ["tinggi", "sedang", "rendah"]},
                    "effect": EFFECT,
                    "why": {"type": "string"},
                },
            },
        },
        "event_risks": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["time_wib", "event", "scenario"],
                "properties": {
                    "time_wib": {"type": "string"},
                    "event": {"type": "string"},
                    "scenario": {"type": "string"},
                },
            },
        },
        "levels": {
            "type": "object",
            "additionalProperties": False,
            "required": ["support", "resistance"],
            "properties": {
                "support": {"type": "array", "items": {"type": "number"}},
                "resistance": {"type": "array", "items": {"type": "number"}},
            },
        },
        "scenarios": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["if_", "then"],
                "properties": {"if_": {"type": "string"}, "then": {"type": "string"}},
            },
        },
    },
}

SYSTEM = """Kamu analis pasar emas (XAU/USD) yang menulis briefing untuk trader ritel Indonesia.
Tulis dalam Bahasa Indonesia yang lugas dan ringkas, tanpa basa-basi.

Tugasmu di setiap briefing:
1. Pilih berita yang benar-benar relevan untuk harga emas dari daftar (rujuk dengan nomor `n`).
   Abaikan berita yang tidak berhubungan. Maksimal 10 berita, urut dari dampak terbesar.
   `effect` = arah dorongan berita itu terhadap emas (bullish/bearish/netral) beserta alasannya
   (jalur transmisi: yield riil, dolar, ekspektasi suku bunga Fed, permintaan safe haven,
   pembelian bank sentral, arus ETF, permintaan fisik India/China, risk-on/off).
2. Faktor makro (Fed & suku bunga, inflasi, tenaga kerja AS, dolar/DXY, yield US10Y,
   geopolitik, kebijakan bank sentral lain, risk sentiment) dan mikro (arus ETF, pembelian
   bank sentral, permintaan fisik, positioning/COT, struktur harga & level teknikal,
   likuiditas sesi). Hanya tulis faktor yang punya dasar di data yang diberikan.
3. Ulas hasil sesi terakhir (label Bullish/Bearish/Sideways sudah dihitung dari harga —
   jelaskan KENAPA harga bergerak begitu, kaitkan dengan berita/event bila ada).
4. Beri bias untuk sesi target (lihat 'Sesi target'). Kalau sinyal campur atau tidak ada
   katalis, jawab 'sideways' dengan keyakinan rendah — jangan memaksakan arah.
5. Event kalender berisiko di depan (jam WIB) + skenario reaksi emas (data lebih tinggi/
   lebih rendah dari forecast).
6. Level support/resistance dekat harga sekarang dari data sesi & harian yang diberikan
   (jangan mengarang level jauh).
7. 2–3 skenario if/then yang bisa dipakai untuk antisipasi.

Jujur soal ketidakpastian. Ini konteks pasar, bukan sinyal entry. Jangan menyebut angka
yang tidak ada di data. Teks `headline` maksimal 1 kalimat; `reason`, `view`, `why`,
`scenario` masing-masing 1–2 kalimat."""


HARI = ["Sen", "Sel", "Rab", "Kam", "Jum", "Sab", "Min"]


def _fmt_ts(t: int) -> str:
    d = datetime.fromtimestamp(t, WIB)
    return f"{HARI[d.weekday()]} {d:%d/%m %H:%M} WIB"


def build_prompt(ctx: dict) -> str:
    lines = [f"Waktu sekarang: {_fmt_ts(ctx['now'])}",
             f"Briefing: {ctx['slot_label']} — Sesi target: {ctx['target_label']}", ""]
    p = ctx["price"]
    lines += ["## Harga XAU/USD",
              f"Sekarang {p['last']:.2f} | hari ini H {p['day_high']:.2f} L {p['day_low']:.2f} | "
              f"kemarin H {p['prev_high']:.2f} L {p['prev_low']:.2f} C {p['prev_close']:.2f} | "
              f"minggu ini H {p['week_high']:.2f} L {p['week_low']:.2f} | ADR20 {p['adr']:.2f}", ""]
    lines.append("## Hasil sesi (dihitung dari candle 15m)")
    for s in ctx["sessions"]:
        lines.append(f"- {s['name']} {s['day']} ({s['hours_wib']}){'' if s['complete'] else ' [BERJALAN]'}: "
                     f"{s['label'].upper()} O {s['open']:.2f} H {s['high']:.2f} L {s['low']:.2f} "
                     f"C {s['close']:.2f} ({s['change']:+.2f}, range {s['range_vs_adr']:.0%} ADR)")
    if ctx.get("prev_eval"):
        e = ctx["prev_eval"]
        lines.append(f"\nOutlook briefing sebelumnya untuk {e['session_name']}: {e['predicted']} → "
                     f"hasil {e['actual']} ({'TEPAT' if e['hit'] else 'MELESET'}).")
    if ctx.get("history"):
        lines += ["", "## Briefing sebelumnya (untuk kesinambungan)"]
        for h in ctx["history"]:
            lines.append(f"- {_fmt_ts(h['t'])} {h['slot_label']}: bias {h['bias']} — {h['headline']}")
    if ctx["macro"]:
        lines += ["", "## Pasar terkait (Yahoo, harian)"]
        for k, v in ctx["macro"].items():
            lines.append(f"- {k}: {v['last']} ({v['chg_1d_pct']:+.2f}% 1h, {v['chg_5d_pct']:+.2f}% 5h)")
    lines += ["", "## Kalender ekonomi (jam WIB; forecast / previous)"]
    for e in ctx["calendar"]:
        tag = "SUDAH RILIS" if e["t"] <= ctx["now"] else "AKAN DATANG"
        lines.append(f"- [{tag}] {_fmt_ts(e['t'])} {e['country']} {e['title']} "
                     f"(impact {e['impact']}, relevansi emas {e['gold']}) f:{e['forecast'] or '-'} "
                     f"p:{e['previous'] or '-'}")
    lines += ["", f"## Berita sejak briefing terakhir ({len(ctx['news'])} item)"]
    for i, n in enumerate(ctx["news"]):
        s = f" — {n['summary'][:200]}" if n["summary"] and n["summary"] not in n["title"] else ""
        lines.append(f"[{i}] {_fmt_ts(n['t'])} | {n['source']} | {n['title']}{s}")
    return "\n".join(lines)


def analyze(ctx: dict, client: anthropic.Anthropic | None = None) -> tuple[dict, dict]:
    """→ (analysis_json, usage_info)."""
    client = client or anthropic.Anthropic()
    prompt = build_prompt(ctx)
    kwargs = dict(
        model=MODEL,
        max_tokens=32000,
        system=SYSTEM,
        output_config={"effort": EFFORT, "format": {"type": "json_schema", "schema": SCHEMA}},
        messages=[{"role": "user", "content": prompt}],
    )
    try:
        with client.beta.messages.stream(betas=["server-side-fallback-2026-07-01"],
                                         fallbacks="default", **kwargs) as stream:
            msg = stream.get_final_message()
    except anthropic.BadRequestError:
        # Fallback server-side tidak tersedia untuk model/akun ini → request biasa.
        with client.messages.stream(**kwargs) as stream:
            msg = stream.get_final_message()
    if msg.stop_reason == "refusal":
        raise RuntimeError("Claude menolak request (refusal)")
    if msg.stop_reason == "max_tokens":
        raise RuntimeError("Output Claude terpotong (max_tokens)")
    text = next(b.text for b in msg.content if b.type == "text")
    data = json.loads(text)
    u = msg.usage
    usage = {"model": msg.model, "input_tokens": u.input_tokens, "output_tokens": u.output_tokens,
             "prompt_chars": len(prompt)}
    return data, usage
