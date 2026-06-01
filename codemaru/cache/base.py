"""Cache protocol shared by all cache backends."""

from __future__ import annotations

from typing import Protocol


class Cache(Protocol):
    """A minimal string-keyed cache with per-entry TTL."""

    def get(self, key: str) -> str | None:
        """Return the cached value, or None if missing/expired."""
        ...

    def set(self, key: str, value: str, ttl_seconds: float) -> None:
        """Store a value under key with a time-to-live in seconds."""
        ...

    def clear(self) -> None:
        """Drop all entries."""
        ...
