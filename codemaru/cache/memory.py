"""A small in-process TTL cache.

Adequate for the Vercel POC (per-instance cache; cold starts and per-region
instances mean misses, which is acceptable). A Redis-backed Cache can replace it
without touching callers.
"""

from __future__ import annotations

import time

# Entry ceiling. A serverless instance can be reused for hours, and the cache is
# keyed by profile, so an unbounded dict grows with every distinct handle ever
# requested on that instance — a slow memory leak that a scraper could drive.
# 1024 summaries is far more than one instance realistically serves hot.
MAX_ENTRIES = 1024


class InMemoryCache:
    """Thread-naive TTL cache. FastAPI request handlers are coroutine-based and
    the operations here are trivial, so no locking is needed for the MVP."""

    def __init__(self, max_entries: int = MAX_ENTRIES) -> None:
        self._store: dict[str, tuple[float, str]] = {}
        self._max_entries = max_entries

    def __len__(self) -> int:
        """Number of retained entries (expired-but-not-yet-evicted included).

        Surfaced by /api/health as a cheap "is this instance warm?" signal.
        """
        return len(self._store)

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
        if key not in self._store and len(self._store) >= self._max_entries:
            self._evict()
        self._store[key] = (time.monotonic() + ttl_seconds, value)

    def clear(self) -> None:
        self._store.clear()

    def _evict(self) -> None:
        """Make room for one new entry: drop everything already expired, then the
        oldest writes until the cache is back under its cap.

        Expiry-first keeps eviction from throwing away entries that are still
        live while dead ones sit in the dict; dicts preserve insertion order, so
        the front of the dict is the oldest write (plain FIFO, not LRU — good
        enough here and free of per-read bookkeeping)."""
        now = time.monotonic()
        for key in [k for k, (expires_at, _) in self._store.items() if now >= expires_at]:
            del self._store[key]
        while len(self._store) >= self._max_entries:
            self._store.pop(next(iter(self._store)))
