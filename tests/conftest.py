from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from codemaru import service
from codemaru.app import app


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture(autouse=True)
def _clear_cache() -> Iterator[None]:
    """Keep the per-process summary cache from leaking between tests."""
    service.clear_cache()
    yield
    service.clear_cache()
