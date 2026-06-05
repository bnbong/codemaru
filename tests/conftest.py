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
def _clear_cache() -> Iterator[None]:
    """Keep the per-process summary cache from leaking between tests."""
    service.clear_cache()
    yield
    service.clear_cache()


@pytest.fixture
def live_mode(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Run with FIXTURE_MODE=false so the live adapter path is exercised."""
    monkeypatch.setenv("FIXTURE_MODE", "false")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
