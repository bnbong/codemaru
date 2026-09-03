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
    # A GitHub handle that doesn't exist isn't a transient failure — retrying it
    # every minute just burns GraphQL quota — so it gets its own, longer negative
    # TTL. Still bounded, since a user can create the account later.
    not_found_cache_ttl_seconds: int = 600
    # How long a last-successful summary is retained for stale fallback.
    stale_ttl_seconds: int = 86400
    # Per-request read budget for live adapters. GitHub's GraphQL query is
    # heavy for active accounts (many repos + a year of contributions): a single
    # page can take 3-4s, so a tight 3s budget silently dropped such profiles to
    # ``unavailable``. 8s gives headroom while staying under the serverless cap;
    # pagination cost is bounded separately (repo-only follow-up pages).
    adapter_timeout_seconds: float = 8.0
    # Ceiling on ONE whole card build, shared by every platform fetch — unlike
    # adapter_timeout_seconds, which each *request* gets to itself. GitHub
    # paginates sequentially (page 1 on the full budget, follow-ups 3s each), so
    # without this the worst case runs well past a serverless function's limit,
    # and a killed function returns no error card and writes no negative cache
    # entry. On expiry the finished platforms are kept and the rest degrade to
    # `unavailable`, so the card still renders (as partial).
    #
    # This bounds the *fetch phase only*. get_summary brackets it with KV calls —
    # one cache read before, then a stale read/write and the cache write after —
    # each bounded by kv_timeout_seconds, so the request's worst case is
    #
    #     kv_timeout_seconds + card_build_timeout_seconds + 2 * kv_timeout_seconds
    #
    # and THAT sum must stay under the platform's function timeout (Vercel's
    # default is 10s), with room left for scoring, rendering and the response.
    # At the defaults: 1 + 6 + 2 = 9s. Raise this only by lowering something else.
    card_build_timeout_seconds: float = 6.0

    # Vercel deployment environment (production / preview / development), injected
    # automatically as VERCEL_ENV. Namespaces the shared cache so a preview deploy
    # never reads or writes production cache entries. "local" when unset.
    vercel_env: str = "local"

    # Vercel KV (Upstash Redis) REST credentials. When set, they back BOTH the
    # adoption-tracking counter AND the shared summary cache; absent locally / in
    # CI, both degrade gracefully (no-op tracking, in-memory cache).
    kv_rest_api_url: str | None = None
    kv_rest_api_token: str | None = None
    # Timeout for the (best-effort) KV calls. Kept short so analytics never
    # delays card rendering; tune up if the KV region is far from the function.
    analytics_timeout_seconds: float = 0.8
    # Timeout for shared-cache KV reads/writes on the card hot path. On a KV
    # outage the call is abandoned after this and the service falls back to a
    # rebuild, so it must stay small; raise only if the KV region is far away.
    kv_timeout_seconds: float = 1.0

    # Shared secret to block requests that bypass the Cloudflare proxy by hitting
    # the raw *.vercel.app origin directly (skipping WAF / rate limits). When set,
    # a Cloudflare *request*-header Transform Rule must inject `X-Origin-Auth:
    # <this>` on every request; the app then 403s any request lacking it. Set it
    # ONLY in production (leave Preview/Dev blank so they stay reachable) and
    # deploy the Cloudflare rule first, or all live traffic gets 403'd.
    origin_shared_secret: str | None = None


@lru_cache
def get_settings() -> Settings:
    """Return a process-wide cached Settings instance."""
    return Settings()
