"""Dedup state di Upstash Redis (REST). Tanpa env → in-memory (untuk test /
dry run lokal)."""

from __future__ import annotations

import os
from datetime import datetime, timezone

_redis = None
_memory: dict[str, str] = {}


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


def _key(cand: dict) -> str:
    if cand.get("kind") == "poc":
        return poc_key(cand["pair"], cand["timeframe"], cand["leg_date"], cand["stage"])
    return signal_key(cand["pair"], cand["timeframe"], cand["pattern"], cand["d_date"], cand.get("stage", "in_prz"))


def _exists(key: str) -> bool:
    r = _client()
    if r is None:
        return key in _memory
    return r.exists(key) > 0


def is_already_signaled(cand: dict) -> bool:
    return _exists(_key(cand))


def earlier_stage_signaled(cand: dict, stages=("approaching", "in_prz")) -> bool:
    """Apakah setup harmonic ini pernah dikirim di salah satu tahap `stages`."""
    return any(_exists(signal_key(cand["pair"], cand["timeframe"], cand["pattern"], cand["d_date"], st))
               for st in stages)


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
