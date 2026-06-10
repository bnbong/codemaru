"""Shared adapter utilities: HTTP client config and a standard User-Agent.

Adapters receive an ``httpx.AsyncClient`` from the service layer so all requests
in one card build share a connection pool and a single timeout budget.
"""

from __future__ import annotations

import httpx

from codemaru import __version__

# Some endpoints (notably solved.ac and LeetCode) reject requests without a
# browser-like User-Agent. The version identifies this client in API logs.
USER_AGENT = f"codemaru/{__version__} (+https://github.com/bnbong/codemaru)"


def build_client(timeout: float) -> httpx.AsyncClient:
    """Create an AsyncClient with a per-request timeout and default headers.

    ``timeout`` is the read budget (the slow part: GitHub's heavy GraphQL query).
    Connect stays short so a dead host fails fast instead of burning the whole
    budget on a stalled handshake.
    """
    return httpx.AsyncClient(
        timeout=httpx.Timeout(timeout, connect=min(timeout, 5.0)),
        headers={"User-Agent": USER_AGENT},
        follow_redirects=True,
    )
