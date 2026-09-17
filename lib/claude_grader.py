"""Grading engine: Claude menilai setup memakai rubric skill
harmonic-pattern-trading, output JSON terstruktur (structured outputs).

Fallback: kalau API error / refusal, pakai rule_grade deterministic supaya
scanner tetap jalan.
"""

from __future__ import annotations

import json
import os
from typing import Literal

import anthropic
from pydantic import BaseModel, Field

from config import settings
from config.pairs import price_decimals
from lib.grading import rule_grade


class GradeResult(BaseModel):
    grade: Literal["A", "B", "C"]
    reasoning: list[str] = Field(description="3-6 bullet, Bahasa Indonesia, faktual")
    entry_model: Literal["Aggressive", "Conservative", "Scaled"]
    invalidation: str
    warnings: list[str] = Field(default_factory=list)
    confidence: Literal["high", "medium", "low"]


SYSTEM_PROMPT = """Kamu Harmonic Analyst (Carney school). Tugasmu MENILAI kualitas satu setup
harmonic yang sudah dideteksi secara mekanis, bukan mencari pattern baru dan
bukan memberi instruksi buy/sell.

RUBRIC GRADE (weakest link — faktor terlemah menentukan grade akhir):

Grade A: pattern Bat/Gartley/Crab; deviasi rasio <2%; PRZ ≥4 Fib level ATAU
3 Fib + 1 structural; searah trend HTF; R:R ≥3:1 ke TP2.
Grade B: pattern Butterfly/Deep Crab/Cypher; deviasi 2-5%; PRZ 3 Fib;
HTF netral; R:R ≥2:1.
Grade C: rasio >5% (invalid), PRZ <3, counter-trend HTF kuat, R:R <2:1.
Cypher & Butterfly maksimum Grade B.

Kamu menerima hasil pengukuran mekanis (rasio, deviasi, PRZ, SL, TP, R:R,
HTF alignment, rule grade). Rule grade sudah menerapkan rubric secara literal.
Tugasmu: konfirmasi atau turunkan grade berdasarkan konteks yang tidak
tertangkap rule (mis. PRZ terlalu lebar, D projected masih jauh, struktur
over-extended, round number besar di PRZ, dsb). JANGAN menaikkan grade di
atas rule grade. Kalau ragu, turunkan.

Cross-asset: crypto (BTC) - SL buffer lebih lebar (>=1.5% beyond X), hindari
entry weekend (volume tipis), PRZ boleh sampai 1%. Metal (XAU) - sensitif
FOMC/CPI/geopolitik, round number kelipatan 50 kuat. Forex - session London/NY.

Timeframe H1 = day trade: session filter lebih penting (London/NY overlap),
hindari Asia session kecuali pair JPY/AUD, dan noise lebih tinggi -> lebih
konservatif saat ragu. M15/M30 = scalping: noise jauh lebih tinggi, hanya
London/NY, spread relatif besar -> R:R harus tetap >=2 setelah spread.
Field STAGE: approaching = user akan pasang LIMIT order di mid PRZ dan
menunggu; in_prz = harga sudah di zona, user entry sekarang tanpa tunggu
konfirmasi -> nilai apakah zona ini layak dieksekusi langsung
(Aggressive/Scaled), bukan sekadar "menunggu".

Pilih entry_model: Scaled kalau PRZ lebar (>0.2%) atau setup high conviction;
Conservative kalau HTF netral/counter atau pattern Butterfly/Cypher;
Aggressive hanya Grade A dengan HTF aligned.

Output HANYA JSON sesuai schema. reasoning = bullet pendek Bahasa Indonesia,
sebut angka konkret. invalidation = satu kalimat level & kondisi void."""


def _fmt(cand: dict) -> str:
    d = price_decimals(cand["pair"])
    f = lambda x: f"{x:.{d}f}"
    p = cand["points"]
    lines = [
        f"PAIR: {cand['pair']}  TF: {cand['timeframe']}  ASSET: {cand.get('asset_class', 'forex')}",
        f"PATTERN: {cand['pattern']} {cand['direction'].upper()}  "
        f"({'projected D' if cand['d_projected'] else 'completed D'})",
        f"X={f(p['X']['price'])} ({p['X']['datetime']})",
        f"A={f(p['A']['price'])} ({p['A']['datetime']})",
        f"B={f(p['B']['price'])} ({p['B']['datetime']})",
        f"C={f(p['C']['price'])} ({p['C']['datetime']})",
    ]
    if p["D"]:
        lines.append(f"D={f(p['D']['price'])} ({p['D']['datetime']})")
    lines.append(f"D ideal={f(cand['d_ideal'])}  harga sekarang={f(cand['current_price'])} "
                 f"({cand['current_datetime']}), jarak ke PRZ={cand['prz_distance_pct']:.2%}, "
                 f"STAGE={cand.get('stage', '?')}")
    lines.append("RATIOS: " + ", ".join(f"{k}={v:.3f}" for k, v in cand["ratios"].items()))
    lines.append("DEVIASI: " + ", ".join(f"{k}={v:.1%}" for k, v in cand["deviations"].items())
                 + f"  (avg {cand['deviation_avg']:.1%}, max {cand['deviation_max']:.1%})")
    prz = cand["prz"]
    lines.append(f"PRZ: {f(prz['low'])} – {f(prz['high'])} (lebar {prz['width_pct']:.2%}), "
                 f"confluence {prz['confluence']} = {prz['fib_count']} fib + {prz['structural_count']} structural")
    for lv in prz["levels"]:
        lines.append(f"  • {lv['name']} @ {f(lv['price'])}")
    lines.append(f"ENTRY (mid PRZ)={f(cand['entry'])}  SL={f(cand['sl'])}")
    lines.append("TP: " + ", ".join(f"{k}={f(v)}" for k, v in cand["tps"].items()))
    lines.append("R:R: " + ", ".join(f"{k}={v:.2f}" for k, v in cand["rr"].items()))
    lines.append(f"HTF ({cand.get('htf_timeframe', '?')}): trend={cand.get('htf_trend', '?')}, "
                 f"alignment={cand.get('htf_alignment', 'neutral')}")
    rg = cand["rule_grade"]
    lines.append(f"RULE GRADE: {rg['grade']}  faktor={json.dumps(rg['factors'])}")
    return "\n".join(lines)


def grade_setup(cand: dict, client: anthropic.Anthropic | None = None) -> dict:
    """Return dict: grade, reasoning[], entry_model, invalidation, warnings[],
    confidence, source ("claude" | "rule-fallback"), model."""
    if "rule_grade" not in cand:
        rule_grade(cand)
    rule = cand["rule_grade"]

    no_key = not settings.env("ANTHROPIC_API_KEY") and not settings.env("ANTHROPIC_AUTH_TOKEN")
    if os.environ.get("GRADER") == "rule" or no_key:
        why = "GRADER=rule" if os.environ.get("GRADER") == "rule" else "ANTHROPIC_API_KEY kosong"
        factors = ", ".join(f"{k} {v}" for k, v in rule["factors"].items())
        return {**rule, "reasoning": [f"Rule-only mode ({why}). Faktor: {factors}"],
                "entry_model": "Conservative", "invalidation": "close beyond X ± buffer",
                "warnings": [], "confidence": "medium", "source": "rule"}

    client = client or anthropic.Anthropic(api_key=settings.env("ANTHROPIC_API_KEY"))
    model = settings.CLAUDE_MODEL
    try:
        resp = client.messages.parse(
            model=model,
            max_tokens=settings.CLAUDE_MAX_TOKENS,
            system=[{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": _fmt(cand)}],
            output_format=GradeResult,
        )
        if resp.stop_reason == "refusal" or resp.parsed_output is None:
            raise RuntimeError(f"no parsed output (stop_reason={resp.stop_reason})")
        out: GradeResult = resp.parsed_output
        grade = out.grade
        # Guardrail: Claude tidak boleh menaikkan grade di atas rule grade.
        order = {"A": 3, "B": 2, "C": 1}
        if order[grade] > order[rule["grade"]]:
            grade = rule["grade"]
        return {
            "grade": grade,
            "reasoning": out.reasoning,
            "entry_model": out.entry_model,
            "invalidation": out.invalidation,
            "warnings": out.warnings,
            "confidence": out.confidence,
            "factors": rule["factors"],
            "source": "claude",
            "model": model,
            "usage": {
                "input": resp.usage.input_tokens,
                "output": resp.usage.output_tokens,
                "cache_read": getattr(resp.usage, "cache_read_input_tokens", 0),
            },
        }
    except Exception as e:  # noqa: BLE001 — grading gagal apa pun sebabnya → rule fallback
        print(f"[warn] Claude grading gagal ({type(e).__name__}: {e}) → fallback rule grade")
        return {
            **rule,
            "reasoning": [f"Rule-based fallback (Claude error: {type(e).__name__})",
                          "Faktor: " + ", ".join(f"{k} {v}" for k, v in rule["factors"].items())],
            "entry_model": "Conservative",
            "invalidation": "Pattern void kalau close beyond X ± buffer",
            "warnings": ["Grade dari rule engine, belum direview Claude"],
            "confidence": "low",
            "source": "rule-fallback",
            "model": model,
        }
