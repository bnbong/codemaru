"""Cache abstraction. MVP ships an in-memory TTL cache; production can swap in
Redis behind the same interface."""

from codemaru.cache.base import Cache
from codemaru.cache.memory import InMemoryCache

__all__ = ["Cache", "InMemoryCache"]
