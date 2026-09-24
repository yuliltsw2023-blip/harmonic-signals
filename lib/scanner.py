"""Shared scan runner. scripts/scan_h4.py & scan_d1.py memanggil run_scan()."""

from __future__ import annotations

import json
import os
import sys
import traceback
from datetime import datetime, timezone

from config import settings
from config.pairs import data_source, is_stock, market_247, symbols_for
from lib.claude_grader import grade_setup
from lib.grading import enrich_levels, htf_alignment, htf_trend, pre_grade, rule_grade
from lib.harmonics import build_candidate, extract_xabcd, match_pattern
from lib.mtf import attach_mtf
from lib.mtf import attach_mtf
from lib.pivots import swing_pivots
from lib.poc import analyze_poc, poc_alignment, rule_grade_poc
from lib.prz import construct_prz
from lib.orders import harmonic_event, poc_event
from lib.exec_rules import (exec_grade_ok, format_exec_notice, harmonic_confirmed, poc_confirmed, session_ok,
                            split_closed)
from lib.state import (backend_name, earlier_poc_stage_signaled, earlier_stage_signaled, is_already_signaled,
                       mark_signaled, mt5_queue_enabled, push_order_event)
from lib.telegram import send_left_notice, send_message, send_poc_signal, send_signal
from lib.twelvedata import TwelveDataClient
from lib.yahoo import YahooClient

INTERVAL_OF = {"M15": "15min", "M30": "30min", "H1": "1h", "H4": "4h", "D1": "1day"}


def is_forex_closed(now: datetime | None = None) -> bool:
    now = now or datetime.now(timezone.utc)
    weekday, hour = now.weekday(), now.hour
    if weekday == 5:
        return True
    if weekday == 6 and hour < 22:
        return True
    if weekday == 4 and hour >= 22:
        return True
    return False


def analyze_candles(pair: str, timeframe: str, candles: list[dict]) -> list[dict]:
    """Pure function: candles → kandidat lengkap (PRZ/SL/TP/RR/pre_grade).
    Tidak menyentuh network. Dipakai scanner & scan_pair & tests."""
    pivots = swing_pivots(candles, settings.PIVOT_LEFT, settings.PIVOT_RIGHT, settings.MIN_LEG_ATR)
    structures = extract_xabcd(pivots, candles)
    out = []
    for match in match_pattern(structures):
        cand = build_candidate(pair, timeframe, match, candles)
        construct_prz(cand, pivots)
        enrich_levels(cand)
        cand["pre_grade"] = pre_grade(cand)
        out.append(cand)
    return out


def _utf8_console() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def run_scan(timeframe: str, pairs: list[str] | None = None, dry_run: bool | None = None) -> int:
    _utf8_console()
    pairs = pairs or symbols_for(timeframe)
    if is_forex_closed():
        skipped = [p for p in pairs if not market_247(p)]
        pairs = [p for p in pairs if market_247(p)]
        print(f"[skip] Forex/metal market closed ({datetime.now(timezone.utc).isoformat()}) "
              f"- {len(skipped)} pair dilewati, {len(pairs)} pair 24/7 tetap di-scan")
        if not pairs:
            return 0
    if dry_run is None:
        dry_run = os.environ.get("DRY_RUN", "false").lower() == "true"
    interval = INTERVAL_OF[timeframe]
    htf_interval = settings.HTF_OF[timeframe]
    print(f"[start] {timeframe} scan · {len(pairs)} pair · DRY_RUN={dry_run} · "
          f"stages={','.join(settings.SIGNAL_STAGES)} · min R:R TP2={settings.MIN_RR_TP2_PREGRADE} · "
          f"state={backend_name()} · model={settings.CLAUDE_MODEL} · closed_only={settings.CLOSED_CANDLE_ONLY} · "
          f"exec harmonic={settings.HARMONIC_EXEC_MODE} poc={settings.POC_EXEC_MODE} min_grade={settings.EXEC_MIN_GRADE} "
          f"session={settings.EXEC_SESSION_UTC or '-'}")
    scan_stamp = datetime.now(timezone.utc).strftime("%H:%M UTC")

    # Client dibuat lazy: scan saham (Yahoo) tidak butuh key Twelve Data.
    clients: dict[str, object] = {}

    def client_for(pair: str):
        src = data_source(pair)
        if src not in clients:
            clients[src] = YahooClient() if src == "yahoo" else TwelveDataClient(api_key=settings.env("TWELVEDATA_API_KEY"))
        return clients[src]

    stats = {k: 0 for k in ("pairs_scanned", "structures_matched", "skipped_pregrade",
                            "skipped_duplicate", "stage_off", "left_notices", "grade_c",
                            "signals_sent", "poc_candidates", "poc_skipped", "poc_sent", "mt5_events",
                            "exec_confirmed", "exec_gate_skip")}
    queue_on = mt5_queue_enabled() and not dry_run

    def queue(ev: dict, pair: str, grade: str | None = None) -> None:
        """Kirim event ke antrean eksekutor MT5 (saham tidak, HFM tidak punya IDX).
        Event "place" digate oleh EXEC_MIN_GRADE; cancel selalu lewat."""
        if not queue_on or is_stock(pair):
            return
        if ev.get("action") == "place" and not exec_grade_ok(grade or ev.get("grade")):
            stats["exec_gate_skip"] += 1
            print(f"[exec-gate] {ev['id']}: grade {grade or ev.get('grade')} < {settings.EXEC_MIN_GRADE}, tidak masuk antrean")
            return
        try:
            push_order_event(ev)
            stats["mt5_events"] += 1
            print(f"[mt5-queue] {ev['action']} {ev['id']}")
        except Exception as e:  # noqa: BLE001 — antrean gagal jangan batalin sinyal
            print(f"[warn] antrean MT5 gagal ({e})")
    errors: list[dict] = []

    for pair in pairs:
        try:
            tdc = client_for(pair)
            candles = tdc.get_candles(pair, interval, outputsize=200)
            stats["pairs_scanned"] += 1
            if settings.CLOSED_CANDLE_ONLY:
                candles, forming = split_closed(candles, interval)
                if forming is not None:
                    print(f"[closed-only] {pair}: candle berjalan {forming['datetime']} dibuang, "
                          f"analisis sampai {candles[-1]['datetime'] if candles else '-'}")
            if len(candles) < 50:
                print(f"[warn] {pair}: hanya {len(candles)} candle, skip")
                continue

            cands = analyze_candles(pair, timeframe, candles)
            stats["structures_matched"] += len(cands)
            htf_candles = None
            ltf_candles = None

            def get_ltf():
                nonlocal ltf_candles
                ltf_iv = settings.LTF_OF.get(timeframe)
                if ltf_iv is None:
                    return []
                if ltf_candles is None:
                    try:
                        ltf_candles = tdc.get_candles(pair, ltf_iv, outputsize=200)
                        if settings.CLOSED_CANDLE_ONLY:
                            ltf_candles, _ = split_closed(ltf_candles, ltf_iv)
                    except Exception as e:  # noqa: BLE001
                        print(f"[warn] {pair}: LTF fetch gagal ({e}), konflik MTF tidak dicek")
                        ltf_candles = []
                return ltf_candles

            def with_mtf(c: dict) -> dict:
                """Isi c["mtf"] (lazy fetch LTF) kalau filter konflik aktif."""
                if settings.MTF_CONFLICT_FILTER:
                    attach_mtf(c, candles, get_ltf(), timeframe)
                    if c["mtf"]["conflict"]:
                        print(f"[mtf-conflict] {pair} {c.get('pattern', 'POC')} {c['direction']}: {c['mtf']['reason']}")
                return c
            ltf_candles = None

            def get_ltf():
                nonlocal ltf_candles
                ltf_iv = settings.LTF_OF.get(timeframe)
                if ltf_iv is None:
                    return []
                if ltf_candles is None:
                    try:
                        ltf_candles = tdc.get_candles(pair, ltf_iv, outputsize=200)
                        if settings.CLOSED_CANDLE_ONLY:
                            ltf_candles, _ = split_closed(ltf_candles, ltf_iv)
                    except Exception as e:  # noqa: BLE001
                        print(f"[warn] {pair}: LTF fetch gagal ({e}), konflik MTF tidak dicek")
                        ltf_candles = []
                return ltf_candles

            def with_mtf(c: dict) -> dict:
                """Isi c["mtf"] (lazy fetch LTF) kalau filter konflik aktif."""
                if settings.MTF_CONFLICT_FILTER:
                    attach_mtf(c, candles, get_ltf(), timeframe)
                    if c["mtf"]["conflict"]:
                        print(f"[mtf-conflict] {pair} {c.get('pattern', 'POC')} {c['direction']}: {c['mtf']['reason']}")
                return c

            def get_htf():
                nonlocal htf_candles
                if htf_candles is None:
                    try:
                        htf_candles = tdc.get_candles(pair, htf_interval, outputsize=settings.HTF_OUTPUTSIZE)
                    except Exception as e:  # noqa: BLE001
                        print(f"[warn] {pair}: HTF fetch gagal ({e}), alignment=neutral")
                        htf_candles = []
                return htf_candles

            for cand in cands:
                cand["scan_datetime"] = scan_stamp
                tag = f"{pair} {cand['pattern']} {cand['direction']} ({'proj' if cand['d_projected'] else 'done'}, {cand.get('stage')})"

                # --- Mode confirmed: entry market saat D sudah pivot terkonfirmasi,
                # independen dari dedup pesan (pesan approaching/in_prz mungkin sudah lewat).
                if (settings.HARMONIC_EXEC_MODE == "confirmed" and queue_on and not cand["d_projected"]
                        and cand.get("stage") in ("in_prz", "left")):
                    ck = dict(cand, stage="confirmed")
                    if not is_already_signaled(ck) and harmonic_confirmed(cand, candles):
                        trend = htf_trend(get_htf()) if get_htf() else "neutral"
                        cand["htf_timeframe"] = htf_interval
                        cand["htf_trend"] = trend
                        cand["htf_alignment"] = htf_alignment(cand, trend)
                        rule_grade(with_mtf(cand))
                        cgrade = grade_setup(cand)["grade"]
                        if cgrade != "C" and exec_grade_ok(cgrade) and session_ok(pair, timeframe):
                            queue(harmonic_event(cand, {"grade": cgrade}), pair, cgrade)
                            mark_signaled(ck)
                            send_message(format_exec_notice(cand, cgrade))
                            stats["exec_confirmed"] += 1
                            print(f"[exec-confirmed] {tag} Grade {cgrade} entry {cand['exec']['entry']} SL {cand['exec']['sl']}")
                        else:
                            print(f"[exec-confirmed-skip] {tag}: grade {cgrade} / sesi {session_ok(pair, timeframe)}")
                            mark_signaled(ck)

                if cand["pre_grade"] == "FAIL":
                    stats["skipped_pregrade"] += 1
                    print(f"[pregrade-fail] {tag}: {cand['pre_grade_reason']}")
                    if cand.get("stage") == "pierced" and queue_on and earlier_stage_signaled(cand):
                        cancel = dict(cand, stage="cancel")
                        if not is_already_signaled(cancel):
                            queue(harmonic_event(cand, action="cancel"), pair)
                            mark_signaled(cancel)
                    continue
                if cand["stage"] not in settings.SIGNAL_STAGES:
                    stats["stage_off"] += 1
                    print(f"[stage-off] {tag}")
                    continue
                if is_already_signaled(cand):
                    stats["skipped_duplicate"] += 1
                    print(f"[dup] {tag}")
                    continue
                if cand["stage"] == "left":
                    # Hanya berguna kalau user pernah dikasih tahu setup ini sebelumnya.
                    if not earlier_stage_signaled(cand):
                        print(f"[left-skip] {tag}: tahap sebelumnya tidak pernah dikirim")
                        continue
                    if dry_run:
                        print(f"[dry_run] Would send left-notice: {tag}")
                    else:
                        send_left_notice(cand)
                        mark_signaled(cand)
                        queue(harmonic_event(cand, action="cancel"), pair)
                        print(f"[sent] left-notice {tag}")
                    stats["left_notices"] += 1
                    continue

                # HTF lazy fetch — hanya untuk kandidat yang lolos pre-grade
                trend = htf_trend(get_htf()) if get_htf() else "neutral"
                cand["htf_timeframe"] = htf_interval
                cand["htf_trend"] = trend
                cand["htf_alignment"] = htf_alignment(cand, trend)
                rule_grade(with_mtf(cand))

                grade = grade_setup(cand)
                print(f"[grade] {tag}: {grade['grade']} (rule {cand['rule_grade']['grade']}, src {grade['source']})")
                if grade["grade"] == "C":
                    stats["grade_c"] += 1
                    continue

                if dry_run:
                    print(f"[dry_run] Would send: {tag} Grade {grade['grade']}")
                else:
                    send_signal(cand, grade, candles)
                    mark_signaled(cand)
                    if settings.HARMONIC_EXEC_MODE == "limit":
                        queue(harmonic_event(cand, grade), pair, grade["grade"])
                    print(f"[sent] {tag} Grade {grade['grade']}")
                stats["signals_sent"] += 1

            # --- Strategi kedua: POC pullback (candle yang sama, 0 request tambahan)
            # POC D1 forex/crypto (profile TPO) nonaktif per backtest; saham (volume asli) tetap.
            if settings.POC_ENABLED and (timeframe in settings.POC_TIMEFRAMES or is_stock(pair)):
                poc = analyze_poc(pair, timeframe, candles)
                if poc is not None:
                    poc["scan_datetime"] = scan_stamp
                    ptag = f"{pair} POC {poc['direction']} [{poc['stage']}]"

                    # Struktur berubah sebelum limit terisi → batalkan pending (sekali).
                    if queue_on and poc["stage"] in settings.POC_CANCEL_ON_STAGE and earlier_poc_stage_signaled(poc):
                        cancel = dict(poc, stage="cancel")
                        if not is_already_signaled(cancel):
                            queue(poc_event(poc, action="cancel"), pair)
                            mark_signaled(cancel)
                            print(f"[poc-cancel] {ptag}")

                    # Mode confirmed: entry market setelah pullback ke POC + candle reaksi.
                    if settings.POC_EXEC_MODE == "confirmed" and queue_on:
                        ck = dict(poc, stage="confirmed")
                        if not is_already_signaled(ck) and poc_confirmed(poc, candles):
                            trend = htf_trend(get_htf()) if get_htf() else "neutral"
                            poc["htf_timeframe"] = htf_interval
                            poc["htf_trend"] = trend
                            poc["htf_alignment"] = poc_alignment(poc, trend)
                            cg = rule_grade_poc(with_mtf(poc))["grade"]
                            if cg != "C" and exec_grade_ok(cg) and session_ok(pair, timeframe):
                                queue(poc_event(poc), pair, cg)
                                mark_signaled(ck)
                                send_message(format_exec_notice(poc, cg))
                                stats["exec_confirmed"] += 1
                                print(f"[exec-confirmed] {ptag} Grade {cg} entry {poc['exec']['entry']} SL {poc['exec']['sl']}")
                            else:
                                print(f"[exec-confirmed-skip] {ptag}: grade {cg} / sesi {session_ok(pair, timeframe)}")
                                mark_signaled(ck)

                    if poc["pre_grade"] == "FAIL":
                        stats["poc_skipped"] += 1
                        print(f"[poc-skip] {ptag}: {poc['pre_grade_reason']}")
                    elif is_already_signaled(poc):
                        stats["skipped_duplicate"] += 1
                        print(f"[dup] {ptag}")
                    else:
                        stats["poc_candidates"] += 1
                        trend = htf_trend(get_htf()) if get_htf() else "neutral"
                        poc["htf_timeframe"] = htf_interval
                        poc["htf_trend"] = trend
                        poc["htf_alignment"] = poc_alignment(poc, trend)
                        g = rule_grade_poc(with_mtf(poc))
                        print(f"[poc-grade] {ptag}: {g['grade']} {g['factors']}")
                        if g["grade"] == "C":
                            stats["grade_c"] += 1
                        elif dry_run:
                            print(f"[dry_run] Would send: {ptag} Grade {g['grade']}")
                            stats["poc_sent"] += 1
                        else:
                            send_poc_signal(poc, candles)
                            mark_signaled(poc)
                            if settings.POC_EXEC_MODE == "limit":
                                queue(poc_event(poc), pair, g["grade"])
                            print(f"[sent] {ptag} Grade {g['grade']}")
                            stats["poc_sent"] += 1

        except Exception as e:  # noqa: BLE001
            errors.append({"pair": pair, "error": str(e), "traceback": traceback.format_exc()})
            print(f"[error] {pair}: {e}", file=sys.stderr)

    summary = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "timeframe": timeframe,
        "dry_run": dry_run,
        **stats,
        "twelvedata_requests": getattr(clients.get("twelvedata"), "request_count", 0),
        "yahoo_requests": getattr(clients.get("yahoo"), "request_count", 0),
        "errors_count": len(errors),
        "errors": [{"pair": e["pair"], "error": e["error"]} for e in errors[:5]],
    }
    print("[summary]", json.dumps(summary, indent=2))

    if errors and len(errors) == len(pairs):
        print("[FATAL] Semua pair error — kemungkinan credentials / API down", file=sys.stderr)
        return 1
    return 0
