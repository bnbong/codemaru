"""Minimal fake httpx client for adapter tests — no network, no extra deps."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


class FakeResponse:
    def __init__(self, status_code: int, payload: Any) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self) -> Any:
        return self._payload


@dataclass
class RecordedCall:
    method: str
    url: str
    params: dict[str, Any] | None = None
    json: Any | None = None
    headers: dict[str, str] | None = None


# A route value is either a single response/exception (returned on every call to
# that URL) or a list consumed in order (for paginated requests).
Route = FakeResponse | Exception | list[FakeResponse | Exception]


@dataclass
class FakeClient:
    """Routes get/post by URL and records every call for assertions.

    Pass a list as a route value to return successive responses for repeated
    calls to the same URL (e.g. GraphQL pagination).
    """

    routes: dict[str, Route]
    calls: list[RecordedCall] = field(default_factory=list)

    def _resolve(self, call: RecordedCall) -> FakeResponse:
        self.calls.append(call)
        entry = self.routes[call.url]
        item = entry.pop(0) if isinstance(entry, list) else entry
        if isinstance(item, Exception):
            raise item
        return item

    async def get(self, url: str, params: dict[str, Any] | None = None) -> FakeResponse:
        return self._resolve(RecordedCall("GET", url, params=params))

    async def post(
        self,
        url: str,
        json: Any | None = None,
        headers: dict[str, str] | None = None,
    ) -> FakeResponse:
        return self._resolve(RecordedCall("POST", url, json=json, headers=headers))
