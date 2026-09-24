"""Dedup state di Upstash Redis (REST). Tanpa env → in-memory (untuk test /
dry run lokal)."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone

_redis = None
_memory: dict[str, str] = {}
_queue: list[str] = []          # antrean order in-memory (test / tanpa Upstash)

ORDER_QUEUE = "mt5:queue"
HALT_KEY = "mt5:halt"


def _client():
    global _redis
    if _redis is not None:
        return _redis
    url = os.environ.get("UPSTASH_REDIS_REST_URL", "").strip()
    token = os.environ.get("UPSTASH_REDIS_REST_TOKEN", "").strip()
    if not url or not token:
        return None
    from upstash_redis import Redis
    _redis = Redis(url=url, token=token)
    return _redis


def signal_key(pair: str, timeframe: str, pattern: str, d_date: str, stage: str = "in_prz") -> str:
    """Dedup harmonic: satu pesan per setup per tahap (approaching / in_prz / left)."""
    safe_pair = pair.replace("/", "_")
    safe_pattern = pattern.replace(" ", "")
    return f"signal:{safe_pair}:{timeframe}:{safe_pattern}:{d_date}:{stage}"


def poc_key(pair: str, timeframe: str, leg_date: str, stage: str) -> str:
    """Dedup POC: satu pesan per leg impulsif per stage (approaching / in_va /
    reacted). Leg baru (HH baru) = key baru."""
    return f"poc:{pair.replace('/', '_')}:{timeframe}:{leg_date}:{stage}"


def _hdate(cand: dict) -> str:
    """Tanggal identitas setup harmonic: C (SETUP_ID_BY_C) atau D (lama)."""
    from config import settings
    if settings.SETUP_ID_BY_C and cand.get("c_date"):
        return cand["c_date"]
    return cand["d_date"]


def _key(cand: dict) -> str:
    if cand.get("kind") == "poc":
        return poc_key(cand["pair"], cand["timeframe"], cand["leg_date"], cand["stage"])
    return signal_key(cand["pair"], cand["timeframe"], cand["pattern"], _hdate(cand), cand.get("stage", "in_prz"))


def _exists(key: str) -> bool:
    r = _client()
    if r is None:
        return key in _memory
    return r.exists(key) > 0


def is_already_signaled(cand: dict) -> bool:
    return _exists(_key(cand))


def earlier_stage_signaled(cand: dict, stages=("approaching", "in_prz")) -> bool:
    """Apakah setup harmonic ini pernah dikirim di salah satu tahap `stages`."""
    return any(_exists(signal_key(cand["pair"], cand["timeframe"], cand["pattern"], _hdate(cand), st))
               for st in stages)


def earlier_poc_stage_signaled(cand: dict, stages=("approaching", "in_va", "reacted")) -> bool:
    """Apakah leg POC ini pernah dikirim di salah satu tahap `stages`."""
    return any(_exists(poc_key(cand["pair"], cand["timeframe"], cand["leg_date"], st)) for st in stages)


def mark_signaled(cand: dict, ttl_seconds: int = 604800) -> None:  # 7 hari
    key = _key(cand)
    value = datetime.now(timezone.utc).isoformat()
    r = _client()
    if r is None:
        _memory[key] = value
        return
    r.set(key, value, ex=ttl_seconds)


def backend_name() -> str:
    return "upstash" if _client() is not None else "memory"


# ---------------------------------------------------------------------------
# Antrean order untuk eksekutor MT5 (executor/) — scanner RPUSH, eksekutor LPOP
# ---------------------------------------------------------------------------

def mt5_queue_enabled() -> bool:
    return os.environ.get("MT5_QUEUE", "true").strip().lower() == "true"


def push_order_event(event: dict) -> None:
    payload = json.dumps(event, ensure_ascii=False)
    r = _client()
    if r is None:
        _queue.append(payload)
        return
    r.rpush(ORDER_QUEUE, payload)


def pop_order_events(max_items: int = 50) -> list[dict]:
    out: list[dict] = []
    r = _client()
    for _ in range(max_items):
        raw = _queue.pop(0) if r is None and _queue else (r.lpop(ORDER_QUEUE) if r is not None else None)
        if raw is None:
            break
        try:
            out.append(json.loads(raw))
        except ValueError:
            continue
    return out


def halt_flag() -> bool:
    r = _client()
    if r is None:
        return _memory.get(HALT_KEY) in ("1", "true")
    v = r.get(HALT_KEY)
    return str(v).lower() in ("1", "true") if v is not None else False
