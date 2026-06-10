"""Application settings, loaded from environment variables (and an optional .env)."""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration. MVP works entirely in fixture mode with no secrets."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # When empty, the web layer derives the base URL from the incoming request
    # origin. Set this only to pin snippet URLs to a fixed public domain.
    public_base_url: str = ""

    # When true, endpoints serve deterministic fixtures and never call external APIs.
    fixture_mode: bool = True

    github_token: str | None = None

    cache_ttl_seconds: int = 3600
    # Failed/degraded (partial/unavailable) results are cached only briefly so a
    # transient outage isn't pinned for the full TTL.
    negative_cache_ttl_seconds: int = 60
    # How long a last-successful summary is retained for stale fallback.
    stale_ttl_seconds: int = 86400
    adapter_timeout_seconds: float = 3.0

    redis_url: str | None = None

    # Vercel KV (Upstash Redis) REST credentials for best-effort adoption
    # tracking. Absent locally / in CI, so tracking degrades to a no-op.
    kv_rest_api_url: str | None = None
    kv_rest_api_token: str | None = None
    # Timeout for the (best-effort) KV calls. Kept short so analytics never
    # delays card rendering; tune up if the KV region is far from the function.
    analytics_timeout_seconds: float = 0.8


@lru_cache
def get_settings() -> Settings:
    """Return a process-wide cached Settings instance."""
    return Settings()
