"""A small in-process TTL cache.

Adequate for the Vercel POC (per-instance cache; cold starts and per-region
instances mean misses, which is acceptable). A Redis-backed Cache can replace it
without touching callers.
"""

from __future__ import annotations

import time


class InMemoryCache:
    """Thread-naive TTL cache. FastAPI request handlers are coroutine-based and
    the operations here are trivial, so no locking is needed for the MVP."""

    def __init__(self) -> None:
        self._store: dict[str, tuple[float, str]] = {}

    def get(self, key: str) -> str | None:
        entry = self._store.get(key)
        if entry is None:
            return None
        expires_at, value = entry
        if time.monotonic() >= expires_at:
            self._store.pop(key, None)
            return None
        return value

    def set(self, key: str, value: str, ttl_seconds: float) -> None:
        self._store[key] = (time.monotonic() + ttl_seconds, value)

    def clear(self) -> None:
        self._store.clear()
