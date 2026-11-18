"""Satu run briefing emas. Dipanggil dari scripts/gold_news.py.

Env:
  TWELVEDATA_API_KEY, ANTHROPIC_API_KEY, UPSTASH_REDIS_REST_URL/TOKEN,
  TELEGRAM_BOT_TOKEN, GOLDNEWS_CHAT_ID, GOLDNEWS_SITE_URL,
  GOLDNEWS_SLOT   paksa slot tertentu (pre_asia/pre_london/pre_ny/post_us/weekly)
  GOLDNEWS_FORCE  true = kirim walau slot itu sudah pernah terkirim
  DRY_RUN         true = analisa & cetak, tanpa simpan/kirim
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from datetime import datetime, timedelta, timezone

from . import analyst, sources, telegram
from .sessions import (SESSION_NAMES, SLOT_BY_KEY, UTC, adr, classify, due_slots,
                       recent_sessions, session_window, slot_id)
from .store import Store

log = logging.getLogger("goldnews")


def _flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes")


def target_of(slot, slot_utc: datetime) -> tuple[str, str | None, str]:
    """(session_key, trading_day, label) yang di-outlook-kan slot ini."""
    if slot.target == "week":
        return "week", None, "Minggu depan"
    for d in (slot_utc.date(), slot_utc.date() + timedelta(days=1)):
        a, b = session_window(slot.target, d)
        if b > slot_utc:
            return slot.target, d.isoformat(), f"Sesi {SESSION_NAMES[slot.target]}"
    raise RuntimeError("target tidak ketemu")


def price_context(c15: list[list[float]], now: datetime) -> dict:
    last = c15[-1]
    day0 = datetime(now.year, now.month, now.day, tzinfo=UTC).timestamp()
    today = [x for x in c15 if x[0] >= day0]
    prev_bars = [x for x in c15 if x[0] < day0]
    pday = datetime.fromtimestamp(prev_bars[-1][0], UTC).date() if prev_bars else None
    prev = [x for x in prev_bars if datetime.fromtimestamp(x[0], UTC).date() == pday]
    monday = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    week = [x for x in c15 if x[0] >= monday.timestamp()] or today or prev
    today = today or prev
    return {
        "last": last[4], "t": last[0],
        "day_high": max(x[2] for x in today), "day_low": min(x[3] for x in today),
        "prev_high": max(x[2] for x in prev) if prev else 0, "prev_low": min(x[3] for x in prev) if prev else 0,
        "prev_close": prev[-1][4] if prev else 0,
        "week_high": max(x[2] for x in week), "week_low": min(x[3] for x in week),
        "adr": adr(c15),
    }


def evaluate_pending(store: Store, metas: list[dict], c15: list[list[float]], now: datetime) -> list[dict]:
    """Isi hasil aktual untuk outlook lama yang sesinya sudah selesai."""
    ref = adr(c15)
    updated = []
    for m in metas:
        if m.get("eval") or m.get("target") in (None, "week") or not m.get("target_day"):
            continue
        a, b = session_window(m["target"], datetime.fromisoformat(m["target_day"]).date())
        if now < b + timedelta(minutes=15):
            continue
        bars = [x for x in c15 if a.timestamp() <= x[0] < b.timestamp()]
        if not bars:
            continue
        o, c = bars[0][1], bars[-1][4]
        h, l = max(x[2] for x in bars), min(x[3] for x in bars)
        actual = classify(o, h, l, c, ref)
        m["eval"] = {"actual": actual, "hit": actual == m["bias"], "change": round(c - o, 2),
                     "session_name": SESSION_NAMES[m["target"]], "predicted": m["bias"]}
        updated.append(m)
    if updated:
        store.save_meta(metas)
    return updated


def main() -> int:
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO").upper(),
                        format="%(asctime)s %(levelname)s %(message)s")
    dry = _flag("DRY_RUN")
    now = datetime.now(UTC)

    forced = os.environ.get("GOLDNEWS_SLOT", "").strip()
    if forced:
        slot = SLOT_BY_KEY[forced]
        slot_utc = now
    else:
        due = due_slots(now)
        if not due:
            log.info("Tidak ada slot jatuh tempo (%s UTC) — selesai.", now.strftime("%H:%M"))
            return 0
        slot, slot_utc = due[0]
    rid = slot_id(slot, slot_utc)
    log.info("Slot %s (%s)", rid, slot.label)

    store = Store()
    if not dry and not _flag("GOLDNEWS_FORCE") and store.was_sent(rid):
        log.info("Slot %s sudah diproses — selesai.", rid)
        return 0

    if True:
        errors: list[str] = []
        # ---- harga
        c15 = sources.fetch_xau_15m(os.environ["TWELVEDATA_API_KEY"], errors)
        if not c15:
            raise RuntimeError("Tidak ada data harga XAU: " + "; ".join(errors))

        # ---- berita sejak run terakhir (min 3 jam, maks 72 jam)
        last_run = float(store.state().get("last_run", 0))
        since_ts = min(now.timestamp() - 3 * 3600, max(last_run, now.timestamp() - 72 * 3600))
        news = sources.fetch_news(datetime.fromtimestamp(since_ts, UTC), errors)[:90]

        # ---- kalender
        cal_week = sources.fetch_calendar(errors)
        horizon = 7 * 86400 if slot.key == "weekly" else 36 * 3600
        cal = [e for e in cal_week
               if now.timestamp() - 24 * 3600 <= e["t"] <= now.timestamp() + horizon
               and (e["gold"] != "rendah" or e["country"] == "USD")]
        cal.sort(key=lambda e: e["t"])

        macro = sources.fetch_macro(errors)
        metas = store.all_meta()
        evaluate_pending(store, metas, c15, now)
        metas.sort(key=lambda m: m["t"])
        prev_eval = next((m["eval"] for m in reversed(metas) if m.get("eval")), None)
        history = metas[-(20 if slot.key == "weekly" else 3):]

        target, target_day, target_label = target_of(slot, slot_utc)
        sessions = recent_sessions(c15, now, count=15 if slot.key == "weekly" else 6)
        price = price_context(c15, now)
        ctx = {
            "now": int(now.timestamp()), "slot_label": slot.label, "target_label": target_label,
            "price": price, "sessions": sessions, "macro": macro, "calendar": cal,
            "news": news, "prev_eval": prev_eval,
            "history": [{"t": h["t"], "slot_label": h["slot_label"], "bias": h["bias"],
                         "headline": h["headline"]} for h in history],
        }
        analysis, usage = analyst.analyze(ctx)
        log.info("Claude: %s in / %s out token", usage["input_tokens"], usage["output_tokens"])

        # gabungkan penilaian Claude ke item berita
        key_news = []
        for k in analysis["key_news"]:
            if 0 <= k["n"] < len(news):
                item = dict(news[k["n"]])
                item.update(impact=k["impact"], effect=k["effect"], why=k["why"])
                key_news.append(item)

        site = os.environ.get("GOLDNEWS_SITE_URL", "").rstrip("/")
        report = {
            "id": rid, "slot": slot.key, "slot_label": slot.label, "t": int(now.timestamp()),
            "target": target, "target_day": target_day, "target_label": target_label,
            "price": price, "sessions": sessions, "macro": macro, "calendar": cal,
            "news": news, "key_news": key_news, "analysis": analysis, "prev_eval": prev_eval,
            "usage": usage, "source_errors": errors,
        }
        meta = {
            "id": rid, "t": report["t"], "slot": slot.key, "slot_label": slot.label,
            "target": target, "target_day": target_day, "bias": analysis["bias"]["direction"],
            "confidence": analysis["bias"]["confidence"], "headline": analysis["headline"],
            "price": price["last"],
            "markers": [{"t": n["t"], "title": n["title"][:140], "effect": n["effect"],
                         "impact": n["impact"]} for n in key_news if n["impact"] != "rendah"],
        }
        text = telegram.format_briefing(report, f"{site}/#r={rid}" if site else "")
        store.save_report(report, meta)
        store.save_calendar(cal_week)
        if dry:
            # Report tetap disimpan (untuk cek website), tapi tidak dikirim & slot
            # tidak ditandai terkirim.
            sys.stdout.buffer.write((text + "\n").encode("utf-8"))
            log.info("DRY_RUN usage=%s errors=%s", json.dumps(usage), errors)
            return 0
        outbox = os.environ.get("GOLDNEWS_OUTBOX")
        if outbox:
            # GitHub Actions: kirim setelah website ter-deploy (lihat send_outbox.py)
            with open(outbox, "w", encoding="utf-8") as f:
                f.write(text)
        else:
            telegram.send(text)
        store.mark_sent(rid, now.timestamp())
        log.info("Terkirim. sumber gagal: %s", errors)
        return 0


if __name__ == "__main__":
    sys.exit(main())
