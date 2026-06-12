from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from codemaru import service
from codemaru.app import create_app
from codemaru.settings import get_settings


@pytest.fixture(autouse=True)
def _isolated_settings(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Keep tests hermetic: pin fixture mode and ignore a developer's local .env
    (e.g. FIXTURE_MODE=false / GITHUB_TOKEN / ORIGIN_SHARED_SECRET), and clear
    caches between tests.

    Env vars take precedence over the .env file in pydantic-settings, so setting
    these here neutralizes a real .env. The `live_mode` fixture overrides
    FIXTURE_MODE back to false for the tests that exercise the live path.
    """
    monkeypatch.setenv("FIXTURE_MODE", "true")
    # Don't let a developer's local origin-guard secret 403 the whole test suite.
    monkeypatch.setenv("ORIGIN_SHARED_SECRET", "")
    # Keep the cache in-memory in tests even if a local .env points at a real KV,
    # so the suite never makes network calls (tests that exercise the KV path
    # monkeypatch codemaru.kv directly instead).
    monkeypatch.setenv("KV_REST_API_URL", "")
    monkeypatch.setenv("KV_REST_API_TOKEN", "")
    get_settings.cache_clear()
    service.clear_cache()
    yield
    get_settings.cache_clear()
    service.clear_cache()


@pytest.fixture
def client(_isolated_settings: None) -> TestClient:
    # Build the app AFTER settings are neutralized (depends on _isolated_settings)
    # so middleware like the origin guard never captures a local .env secret.
    return TestClient(create_app())


@pytest.fixture
def live_mode(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Run with FIXTURE_MODE=false so the live adapter path is exercised."""
    monkeypatch.setenv("FIXTURE_MODE", "false")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
