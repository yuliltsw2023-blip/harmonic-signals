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


def manual_event(symbol: str, side: str, entry: float, sl: float, tp1: float, tp2: float | None,
                 timeframe: str, setup: str, order: str = "limit", exit_mode: str = "tp",
                 grade: str = "A", expires_hours: float | None = None,
                 risk_pct: float | None = None, be_r: float = 1.0) -> dict:
    """Event 'place' untuk setup yang dikonfirmasi manual (scripts/manual/queue_manual.py).

    exit_mode "trail" = id "h:" → EA v1.2 pakai trailing swing di `timeframe` (tanpa TP);
    "tpbe" = id "m:" + be_r → EA v1.3: satu posisi ke TP1, SL→BE setelah +be_r R;
    "tp" = id "m:" → EA pasang TP1 (dan TP2 kalau lot bisa dibagi dua).
    risk_pct (EA v1.3, dibatasi InpMaxRiskPct) menimpa risiko dari grade
    (Grade A = InpRiskPct penuh, B = setengahnya).
    """
    if side not in ("buy", "sell"):
        raise ValueError("side harus buy/sell")
    if (side == "buy" and not sl < entry < tp1) or (side == "sell" and not sl > entry > tp1):
        raise ValueError("urutan SL/entry/TP1 tidak cocok dengan arah")
    now = datetime.now(timezone.utc)
    prefix = "h" if exit_mode == "trail" else "m"
    ev = {
        "id": f"{prefix}:{symbol}:{timeframe}:{setup}:{now:%Y%m%d%H%M}",
        "action": "place",
        "kind": "harmonic" if exit_mode == "trail" else "manual",
        "symbol": symbol,
        "timeframe": timeframe,
        "side": side,
        "stage": "manual",
        "created_at": now.isoformat(timespec="seconds"),
        "expires_hours": expires_hours or EXPIRY_HOURS.get(timeframe, 24),
        "label": f"{symbol} {setup} {'BUY' if side == 'buy' else 'SELL'} {timeframe} (manual)",
        "entry": float(entry),
        "sl": float(sl),
        "tp1": float(tp1),
        "tp2": float(tp2 if tp2 is not None else tp1),
        "grade": grade,
        "prz": [float(min(entry, sl)), float(max(entry, sl))],
        "order": order,
        "exec_mode": "confirmed" if order == "market" else "limit",
    }
    if risk_pct:
        ev["risk_pct"] = float(risk_pct)
    if exit_mode == "tpbe":
        ev["be_r"] = float(be_r)
    return ev


def is_expired(ev: dict, now: datetime | None = None) -> bool:
    now = now or datetime.now(timezone.utc)
    created = datetime.fromisoformat(ev["created_at"])
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    return (now - created).total_seconds() > ev.get("expires_hours", 24) * 3600
