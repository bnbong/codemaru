from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from codemaru import service
from codemaru.app import app
from codemaru.settings import get_settings


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture(autouse=True)
def _isolated_settings(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Keep tests hermetic: pin fixture mode and ignore a developer's local .env
    (e.g. FIXTURE_MODE=false / GITHUB_TOKEN), and clear caches between tests.

    Env vars take precedence over the .env file in pydantic-settings, so setting
    FIXTURE_MODE here neutralizes a real .env. The `live_mode` fixture overrides
    it back to false for the tests that exercise the live path.
    """
    monkeypatch.setenv("FIXTURE_MODE", "true")
    get_settings.cache_clear()
    service.clear_cache()
    yield
    get_settings.cache_clear()
    service.clear_cache()


@pytest.fixture
def live_mode(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Run with FIXTURE_MODE=false so the live adapter path is exercised."""
    monkeypatch.setenv("FIXTURE_MODE", "false")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
