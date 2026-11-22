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

from . import analyst, charts, smc, sources, telegram, trade
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


def build_trade(ctx: dict, analysis: dict, c15: list, metas: list[dict], now: datetime,
                errors: list[str]) -> tuple[dict, list[dict]]:
    """Rencana trading + gambar chart. Juga menilai rencana lama (metas diubah di tempat)."""
    key = os.environ["TWELVEDATA_API_KEY"]
    m5 = sources.fetch_xau(key, errors, "5min", 3000)
    h1 = sources.fetch_xau(key, errors, "1h", 500)
    h4 = sources.fetch_xau(key, errors, "4h", 400)
    if not (m5 and h1 and h4):
        raise RuntimeError("candle M5/H1/H4 tidak lengkap")
    ts = now.timestamp()

    # nilai rencana lama
    for m in metas:
        for i, p in enumerate(m.get("plans") or []):
            evals = m.setdefault("plan_evals", [None] * len(m["plans"]))
            if evals[i] is None:
                res = trade.evaluate(p, m["t"], m5, ts)
                if res:
                    evals[i] = res
                    m["plan_evals_new"] = True

    tfs = [trade.tf_summary(n, b) for n, b in (("H4", h4), ("H1", h1), ("M15", c15), ("M5", m5))]
    pc = ctx["price"]
    asia = next((s for s in reversed(ctx["sessions"]) if s["session"] == "asia"), None)
    levels = {"High hari ini": pc["day_high"], "Low hari ini": pc["day_low"],
              "High kemarin": pc["prev_high"], "Low kemarin": pc["prev_low"],
              "Close kemarin": pc["prev_close"], "High minggu": pc["week_high"], "Low minggu": pc["week_low"]}
    if asia:
        levels.update({"High Asia": asia["high"], "Low Asia": asia["low"]})
    price = m5[-1][4]
    # ---- Smart Money Concepts: H1 bias & liquidity, M15 struktur + POI, M5 konfirmasi
    named = {k: v for k, v in levels.items() if v and ("High" in k or "Low" in k)}
    a1 = smc.analyze(h1, "H1", 3, named, lookback=24)
    a15 = smc.analyze(c15, "M15", 2, named, lookback=48)
    a5 = smc.analyze(m5, "M5", 2, lookback=72)
    checks = {d: smc.checklist(d, a1, a15, a5, c15, m5, price) for d in ("sell", "buy")}
    smc_lines = smc.describe(a1, price) + [""] + smc.describe(a15, price) + [""] +         smc.describe(a5, price, zones=False) + ["", "### Checklist mekanis (window 8 jam)"]
    for d, ck in checks.items():
        def st(k):
            v = ck[k]
            if not v:
                return "BELUM"
            return f"YA ({v.get('kind', v.get('name', ''))} {v.get('level', v.get('lo', '')):.2f} @ {smc.fmt_ts(v['t'])})"
        smc_lines.append(f"{d.upper()}: liquidity {st('liquidity')} → structure {st('structure')} → "
                         f"POI {st('poi')} → konfirmasi M5 {st('confirmation')}"
                         + (f" · BASI: {'; '.join(ck['stale'])}" if ck['stale'] else "")
                         + (" · LENGKAP" if ck["complete"] else ""))
    pctx = {"now": int(ts), "target_label": ctx["target_label"], "price": price, "levels": levels, "tfs": tfs,
            "briefing": {"bias": analysis["bias"]["direction"], "confidence": analysis["bias"]["confidence"],
                         "headline": analysis["headline"], "event_risks": analysis["event_risks"]},
            "smc": smc_lines}
    data, usage = trade.plan(pctx)
    atr_of = {s["tf"]: s["atr"] for s in tfs}
    plans = []
    for p in data["plans"][:2]:
        tf = "M15" if p["style"] == "intraday" else "M5"
        plans.append(trade.validate(p, price, atr_of[tf], atr_of["H1"], checks))
    block = {"t": int(ts), "price": price, "trend": data["trend"], "plans": plans, "usage": usage,
             "atr": atr_of, "smc": {"h1": a1.trend, "m15": a15.trend, "m5": a5.trend,
                                    "checks": {d: {k: bool(c[k]) for k in ("liquidity", "structure", "poi",
                                                                             "confirmation", "complete")}
                                               for d, c in checks.items()}}}

    prev = next((m for m in reversed(metas) if m.get("plan_evals") and any(m["plan_evals"])), None)
    images = []
    out_dir = os.path.dirname(os.environ.get("GOLDNEWS_OUTBOX") or os.path.join(
        os.environ.get("TEMP", "/tmp"), "x")) or "."
    for i, p in enumerate(plans):
        bars = c15 if p["tf"] == "M15" else m5
        png, src = charts.render(p, bars, int(ts), errors)
        p["chart"] = src
        path = os.path.join(out_dir, f"plan_{i}.png")
        with open(path, "wb") as f:
            f.write(png)
        images.append({"type": "photo", "path": path,
                       "caption": telegram.format_plan(p, data["trend"] if i == 0 else None,
                                                       prev if i == 0 else None)})
    return block, images


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

        # ---- rencana trading (intraday M15 + scalping M5), kecuali rekap mingguan
        trade_block, images = None, []
        if slot.key != "weekly":
            try:
                trade_block, images = build_trade(ctx, analysis, c15, metas, now, errors)
            except Exception as e:  # noqa: BLE001 — briefing tetap dikirim tanpa rencana
                log.exception("Rencana trading gagal")
                errors.append(f"trade: {str(e)[:120]}")
        if any(m.get("plan_evals_new") for m in metas):
            for m in metas:
                m.pop("plan_evals_new", None)
            store.save_meta(metas)

        site = os.environ.get("GOLDNEWS_SITE_URL", "").rstrip("/")
        report = {
            "id": rid, "slot": slot.key, "slot_label": slot.label, "t": int(now.timestamp()),
            "target": target, "target_day": target_day, "target_label": target_label,
            "price": price, "sessions": sessions, "macro": macro, "calendar": cal,
            "news": news, "key_news": key_news, "analysis": analysis, "prev_eval": prev_eval,
            "usage": usage, "source_errors": errors, "trade": trade_block,
        }
        meta = {
            "id": rid, "t": report["t"], "slot": slot.key, "slot_label": slot.label,
            "target": target, "target_day": target_day, "bias": analysis["bias"]["direction"],
            "confidence": analysis["bias"]["confidence"], "headline": analysis["headline"],
            "price": price["last"],
            "markers": [{"t": n["t"], "title": n["title"][:140], "effect": n["effect"],
                         "impact": n["impact"]} for n in key_news if n["impact"] != "rendah"],
            "plans": [{k: p.get(k) for k in ("style", "tf", "action", "order", "entry", "sl", "tp1", "tp2",
                                             "valid_hours", "risk")}
                      for p in (trade_block or {}).get("plans", [])],
        }
        text = telegram.format_briefing(report, f"{site}/#r={rid}" if site else "")
        store.save_report(report, meta)
        store.save_calendar(cal_week)
        # foto kotak sesi (3 sesi terakhir) — sebelum foto rencana trading
        session_img = []
        try:
            png, src = charts.render_sessions(sessions, c15, int(now.timestamp()), errors)
            spath = os.path.join(os.path.dirname(os.environ.get("GOLDNEWS_OUTBOX") or os.path.join(
                os.environ.get("TEMP", "/tmp"), "x")) or ".", "sessions.png")
            with open(spath, "wb") as f:
                f.write(png)
            session_img = [{"type": "photo", "path": spath, "caption": telegram.format_sessions(sessions, src)}]
        except Exception as e:  # noqa: BLE001
            log.exception("Chart sesi gagal")
            errors.append(f"chart sesi: {str(e)[:100]}")
        messages = [{"type": "text", "text": text}] + session_img + images
        outbox = os.environ.get("GOLDNEWS_OUTBOX", "")
        if dry:
            # Report tetap disimpan (untuk cek website), tapi tidak dikirim & slot
            # tidak ditandai terkirim.
            sys.stdout.buffer.write((text + "\n").encode("utf-8"))
            for m in images:
                sys.stdout.buffer.write(f"\n[FOTO {m['path']}]\n{m['caption']}\n".encode("utf-8"))
            log.info("DRY_RUN usage=%s errors=%s", json.dumps(usage), errors)
            return 0
        if outbox:
            # GitHub Actions: kirim setelah website ter-deploy (lihat send_outbox.py)
            with open(outbox, "w", encoding="utf-8") as f:
                json.dump(messages, f, ensure_ascii=False)
        else:
            telegram.send_all(messages)
        store.mark_sent(rid, now.timestamp())
        log.info("Terkirim. sumber gagal: %s", errors)
        return 0


if __name__ == "__main__":
    sys.exit(main())
