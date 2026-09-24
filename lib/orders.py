"""Spesifikasi order untuk eksekutor MT5 (executor/).

Scanner (GitHub Actions) menulis event ke antrean Upstash `mt5:queue`;
eksekutor di PC user membaca antrean itu dan memasang pending limit order.
Satu setup = satu id; event "place" idempoten (approaching lalu in_prz
untuk setup yang sama tidak bikin order dobel), "cancel" membatalkan pending
yang belum terisi.
"""

from __future__ import annotations

from datetime import datetime, timezone

from config import settings

# Pending limit dibatalkan otomatis kalau tidak terisi dalam N jam sejak dibuat.
EXPIRY_HOURS = {"M15": 2, "M30": 4, "H1": 8, "H4": 36, "D1": 24 * 5}


def setup_id(cand: dict) -> str:
    if cand.get("kind") == "poc":
        return f"p:{cand['pair']}:{cand['timeframe']}:{cand['leg_date']}"
    key_date = cand.get("c_date") if settings.SETUP_ID_BY_C and cand.get("c_date") else cand["d_date"]
    return f"h:{cand['pair']}:{cand['timeframe']}:{cand['pattern'].replace(' ', '')}:{key_date}"


def _base(cand: dict, action: str) -> dict:
    return {
        "id": setup_id(cand),
        "action": action,
        "kind": cand.get("kind", "harmonic"),
        "symbol": cand["pair"],
        "timeframe": cand["timeframe"],
        "side": "buy" if cand["direction"] == "bull" else "sell",
        "stage": cand.get("stage"),
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "expires_hours": EXPIRY_HOURS.get(cand["timeframe"], 24),
    }


def harmonic_event(cand: dict, grade: dict | None = None, action: str = "place") -> dict:
    ev = _base(cand, action)
    ev["label"] = f"{cand['pair']} {cand['pattern']} {'BULL' if cand['direction'] == 'bull' else 'BEAR'} {cand['timeframe']}"
    if action == "place":
        ex = cand.get("exec") or {}
        ev.update({
            "entry": float(ex.get("entry", cand["entry"])),
            "sl": float(ex.get("sl", cand["sl"])),
            "tp1": float((ex.get("tps") or cand["tps"])["tp1"]),
            "tp2": float((ex.get("tps") or cand["tps"])["tp2"]),
            "grade": (grade or cand.get("rule_grade") or {}).get("grade", "B"),
            "prz": [float(cand["prz"]["low"]), float(cand["prz"]["high"])],
            "order": ex.get("order", "limit"),
            "exec_mode": ex.get("mode", "limit"),
        })
    return ev


def poc_event(cand: dict, action: str = "place") -> dict:
    ev = _base(cand, action)
    ev["label"] = f"{cand['pair']} POC {'BUY' if cand['direction'] == 'bull' else 'SELL'} {cand['timeframe']}"
    if action == "place":
        ex = cand.get("exec") or {}
        ev.update({
            "entry": float(ex.get("entry", cand["poc"])),
            "sl": float(ex.get("sl", cand["sl"])),
            "tp1": float(cand["tps"]["tp1"]),
            "tp2": float(cand["tps"]["tp2"]),
            "grade": (cand.get("grade") or {}).get("grade", "B"),
            "prz": [float(min(cand["val"], cand["vah"])), float(max(cand["val"], cand["vah"]))],
            "order": ex.get("order", "limit"),
            "exec_mode": ex.get("mode", "limit"),
        })
    return ev


def is_expired(ev: dict, now: datetime | None = None) -> bool:
    now = now or datetime.now(timezone.utc)
    created = datetime.fromisoformat(ev["created_at"])
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    return (now - created).total_seconds() > ev.get("expires_hours", 24) * 3600
