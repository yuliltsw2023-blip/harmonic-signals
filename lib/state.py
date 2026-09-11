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
    url = os.environ.get("UPSTASH_REDIS_REST_URL")
    token = os.environ.get("UPSTASH_REDIS_REST_TOKEN")
    if not url or not token:
        return None
    from upstash_redis import Redis
    _redis = Redis(url=url, token=token)
    return _redis


def signal_key(pair: str, timeframe: str, pattern: str, d_date: str) -> str:
    safe_pair = pair.replace("/", "_")
    safe_pattern = pattern.replace(" ", "")
    return f"signal:{safe_pair}:{timeframe}:{safe_pattern}:{d_date}"


def _key(cand: dict) -> str:
    return signal_key(cand["pair"], cand["timeframe"], cand["pattern"], cand["d_date"])


def is_already_signaled(cand: dict) -> bool:
    key = _key(cand)
    r = _client()
    if r is None:
        return key in _memory
    return r.exists(key) > 0


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
