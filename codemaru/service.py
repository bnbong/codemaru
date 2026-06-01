"""Card service: turns a validated ProfileInput into a CodemaruSummary.

This is where input → (cache | adapters) → scoring → summary is coordinated, so
routes stay thin. In fixture mode it serves deterministic sample data; live
adapters slot in here in a later PR behind the same cache boundary.

The cache is keyed by profile only (not theme/compact): those affect rendering,
not the underlying data, and rendering is cheap.
"""

from __future__ import annotations

from codemaru.cache import InMemoryCache
from codemaru.core.scoring import SCORE_VERSION
from codemaru.core.summary import build_summary
from codemaru.fixtures.demo import FIXED_TIMESTAMP, resolve_fixture_bundle
from codemaru.models.input import ProfileInput
from codemaru.models.summary import CodemaruSummary
from codemaru.settings import get_settings

# Flip to True only when real GitHub/solved.ac/LeetCode adapters exist. Until
# then `FIXTURE_MODE=false` is a configuration error rather than a silent
# fixture-as-live response.
LIVE_ADAPTERS_AVAILABLE = False

_cache = InMemoryCache()


class LiveDataUnavailableError(RuntimeError):
    """Raised when live data is requested but no adapters are implemented yet."""


def effective_mode() -> str:
    """The mode the service can actually serve right now (never a lie)."""
    settings = get_settings()
    if settings.fixture_mode:
        return "fixture"
    return "live" if LIVE_ADAPTERS_AVAILABLE else "unavailable"


def _cache_key(profile: ProfileInput) -> str:
    return f"summary:v{SCORE_VERSION}:{profile.github}|{profile.boj}|{profile.leetcode}"


def get_summary(profile: ProfileInput) -> CodemaruSummary:
    """Return the summary for a profile, using the cache when warm.

    Raises LiveDataUnavailableError if live data is requested
    (``FIXTURE_MODE=false``) before adapters exist, so fixture data is never
    presented as if it were live.
    """
    settings = get_settings()
    if not settings.fixture_mode and not LIVE_ADAPTERS_AVAILABLE:
        raise LiveDataUnavailableError(
            "live adapters are not implemented yet; set FIXTURE_MODE=true"
        )

    key = _cache_key(profile)
    cached = _cache.get(key)
    if cached is not None:
        return CodemaruSummary.model_validate_json(cached)

    summary = _build(profile)
    # Cache the field-name form so it round-trips back through validation; the
    # JSON endpoint serializes with aliases separately for the public response.
    _cache.set(key, summary.model_dump_json(), settings.cache_ttl_seconds)
    return summary


def _build(profile: ProfileInput) -> CodemaruSummary:
    # MVP: only fixture mode exists. Live adapters will branch here once
    # LIVE_ADAPTERS_AVAILABLE is True and assemble a real SnapshotBundle.
    bundle = resolve_fixture_bundle(profile)
    return build_summary(profile, bundle, FIXED_TIMESTAMP)


def clear_cache() -> None:
    """Drop all cached summaries (used in tests)."""
    _cache.clear()
