"""Structured logging: every event is one parseable JSON line, and nothing leaks.

Serverless logs are stdout, so the value of these events is entirely in being
machine-readable — a line that isn't JSON is a line nobody can query.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any

import pytest

from codemaru import analytics, service, telemetry
from codemaru.models.input import ProfileInput
from codemaru.models.snapshot import (
    GitHubSnapshot,
    LeetCodeSnapshot,
    LeetCodeSolved,
    PlatformStatus,
    SolvedAcSnapshot,
)

_TS = datetime(2026, 5, 31, tzinfo=UTC)


def _events(caplog: pytest.LogCaptureFixture, name: str) -> list[dict[str, Any]]:
    """Every record from the codemaru logger, parsed, filtered by event name."""
    parsed = []
    for record in caplog.records:
        if record.name != "codemaru":
            continue
        payload = json.loads(record.getMessage())  # must be valid JSON
        if payload["event"] == name:
            parsed.append(payload)
    return parsed


@pytest.fixture
def capture(caplog: pytest.LogCaptureFixture) -> pytest.LogCaptureFixture:
    caplog.set_level(logging.INFO, logger="codemaru")
    return caplog


def _github(login: str) -> GitHubSnapshot:
    return GitHubSnapshot(
        status=PlatformStatus.OK,
        fetched_at=_TS,
        login=login,
        public_repos=10,
        total_stars=500,
        total_forks=40,
        followers=80,
        total_commits=900,
        total_pull_requests=70,
        total_issues=30,
        total_reviews=40,
        contributed_repos=12,
        active_days=150,
        longest_streak=20,
        language_count=5,
    )


async def _ok_github(login: str, **_: Any) -> GitHubSnapshot:
    return _github(login)


async def _ok_leetcode(username: str, **_: Any) -> LeetCodeSnapshot:
    return LeetCodeSnapshot(
        status=PlatformStatus.OK,
        fetched_at=_TS,
        username=username,
        solved=LeetCodeSolved(easy=10, medium=5, hard=1),
        ranking=1000,
        contest_rating=1500,
    )


# --- log_event / formatter ---------------------------------------------------


def test_log_event_emits_one_json_line(capture: pytest.LogCaptureFixture):
    telemetry.log_event("demo", platform="github", ms=12.5)
    payload = json.loads(capture.records[-1].getMessage())
    assert payload == {"event": "demo", "platform": "github", "ms": 12.5}
    assert "\n" not in capture.records[-1].getMessage()


def test_log_event_is_a_noop_when_the_logger_is_disabled(caplog: pytest.LogCaptureFixture):
    caplog.set_level(logging.CRITICAL, logger="codemaru")
    telemetry.log_event("demo", value=1)
    assert [r for r in caplog.records if r.name == "codemaru"] == []


def test_log_event_survives_an_unserializable_field(capture: pytest.LogCaptureFixture):
    # `default=str` is the safety net: telemetry must never raise on the hot path.
    telemetry.log_event("demo", when=_TS, status=PlatformStatus.PARTIAL)
    payload = json.loads(capture.records[-1].getMessage())
    assert payload["status"] == "partial"
    assert payload["when"].startswith("2026-05-31")


def test_formatter_passes_structured_records_through_verbatim():
    formatter = telemetry.JsonLineFormatter()
    record = logging.LogRecord(
        "codemaru", logging.INFO, __file__, 1, '{"event":"demo"}', None, None
    )
    record.codemaru_structured = True  # type: ignore[attr-defined]
    assert formatter.format(record) == '{"event":"demo"}'


def test_formatter_wraps_unstructured_records_as_json():
    formatter = telemetry.JsonLineFormatter()
    record = logging.LogRecord("httpx", logging.WARNING, __file__, 1, "hi %s", ("there",), None)
    payload = json.loads(formatter.format(record))
    assert payload == {
        "event": "log",
        "level": "WARNING",
        "logger": "httpx",
        "message": "hi there",
    }


def test_log_exception_is_a_noop_when_the_logger_is_disabled(caplog: pytest.LogCaptureFixture):
    caplog.set_level(logging.CRITICAL, logger="codemaru")
    try:
        raise RuntimeError("boom")
    except RuntimeError:
        telemetry.log_exception("card_error", handle="octocat")
    assert [r for r in caplog.records if r.name == "codemaru"] == []


def test_log_exception_splices_the_traceback_into_the_same_object(
    capture: pytest.LogCaptureFixture,
):
    formatter = telemetry.JsonLineFormatter()
    try:
        raise RuntimeError("boom")
    except RuntimeError:
        telemetry.log_exception("card_error", handle="octocat")
    record = capture.records[-1]
    payload = json.loads(formatter.format(record))
    assert payload["event"] == "card_error"
    assert payload["handle"] == "octocat"
    assert "RuntimeError: boom" in payload["error"]


def test_configure_logging_does_not_double_configure():
    root = logging.getLogger()
    before = list(root.handlers)
    level = telemetry.logger.level
    try:
        telemetry.configure_logging()
        telemetry.configure_logging()
        # pytest already owns the root logger during a test run, so ours stays out.
        assert list(root.handlers) == before
    finally:
        telemetry.logger.setLevel(level)


def test_configure_logging_still_enables_our_logger_when_the_host_owns_logging():
    # Regression: the early return skipped the level too, so on a host that
    # pre-configures the root logger (Vercel's runtime may) every log_event was
    # dropped by the isEnabledFor(INFO) guard and the app logged nothing at all.
    root = logging.getLogger()
    assert root.handlers  # pytest owns logging during a test run
    level = telemetry.logger.level
    try:
        telemetry.logger.setLevel(logging.WARNING)
        telemetry.configure_logging()
        assert telemetry.logger.level == logging.INFO
        assert telemetry.logger.isEnabledFor(logging.INFO)
    finally:
        telemetry.logger.setLevel(level)


def test_configure_logging_attaches_a_json_handler_when_nothing_owns_logging():
    # The other branch: on a bare process we install the stdout JSON handler, so
    # serverless log lines are parseable from the first request.
    root = logging.getLogger()
    handlers = list(root.handlers)
    level = telemetry.logger.level
    root.handlers = []
    try:
        telemetry.configure_logging()
        assert len(root.handlers) == 1
        assert isinstance(root.handlers[0].formatter, telemetry.JsonLineFormatter)
        assert telemetry.logger.level == logging.INFO
    finally:
        root.handlers = handlers
        telemetry.logger.setLevel(level)


# --- adapter events ----------------------------------------------------------


async def test_adapter_event_on_a_successful_fetch(capture: pytest.LogCaptureFixture):
    from typing import cast

    import httpx

    from codemaru.adapters.github import GITHUB_GRAPHQL_URL, fetch_github
    from tests.adapters.fakes import FakeClient, FakeResponse

    payload = {
        "login": "octocat",
        "followers": {"totalCount": 3},
        "repositories": {"totalCount": 1, "nodes": [], "pageInfo": {"hasNextPage": False}},
        "contributionsCollection": {"contributionCalendar": {"weeks": []}},
    }
    client = FakeClient({GITHUB_GRAPHQL_URL: FakeResponse(200, {"data": {"user": payload}})})
    await fetch_github("octocat", token="t", fetched_at=_TS, client=cast(httpx.AsyncClient, client))

    (event,) = _events(capture, "adapter")
    assert event["platform"] == "github"
    assert event["handle"] == "octocat"
    assert event["status"] == "ok"
    assert event["note"] is None
    assert isinstance(event["ms"], int | float)


async def test_adapter_event_on_a_degraded_fetch(
    capture: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
):
    # A failure is exactly what the log is for; it must not be the silent path.
    from codemaru.adapters import solvedac
    from codemaru.adapters.solvedac import SHOW_URL, fetch_solvedac
    from tests.adapters.fakes import FakeResponse, async_session_factory

    monkeypatch.setattr(
        solvedac, "AsyncSession", async_session_factory({SHOW_URL: FakeResponse(404, {})})
    )
    await fetch_solvedac("ghost", fetched_at=_TS, timeout=5)

    (event,) = _events(capture, "adapter")
    assert event["platform"] == "solvedac"
    assert event["handle"] == "ghost"
    assert event["status"] == "unavailable"
    assert event["note"] == "http 404"


# --- build event -------------------------------------------------------------


async def test_build_event_reports_per_platform_statuses(
    capture: pytest.LogCaptureFixture, live_mode: None, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(service, "fetch_github", _ok_github)
    monkeypatch.setattr(service, "fetch_leetcode", _ok_leetcode)

    await service.get_summary(ProfileInput(github="octocat", leetcode="lc"))

    (event,) = _events(capture, "build")
    assert event["handle"] == "octocat"
    assert event["statuses"] == {"github": "ok", "leetcode": "ok"}
    assert event["timed_out"] == []
    assert isinstance(event["ms"], int | float)


async def test_build_event_names_the_platforms_the_budget_cut_short(
    capture: pytest.LogCaptureFixture, live_mode: None, monkeypatch: pytest.MonkeyPatch
):
    import asyncio

    from codemaru.settings import get_settings

    monkeypatch.setenv("CARD_BUILD_TIMEOUT_SECONDS", "0.05")
    get_settings.cache_clear()

    async def never_returns(handle: str, **_: Any) -> SolvedAcSnapshot:
        await asyncio.sleep(3600)
        raise AssertionError("unreachable")  # pragma: no cover

    monkeypatch.setattr(service, "fetch_github", _ok_github)
    monkeypatch.setattr(service, "fetch_solvedac", never_returns)

    await service.get_summary(ProfileInput(github="octocat", boj="baek"))

    (event,) = _events(capture, "build")
    assert event["timed_out"] == ["solvedac"]
    assert event["statuses"]["solvedac"] == "unavailable"
    assert event["statuses"]["github"] == "ok"


# --- cache events ------------------------------------------------------------


async def test_cache_event_reports_miss_then_hit(capture: pytest.LogCaptureFixture):
    from codemaru.settings import get_settings

    profile = ProfileInput(github="octocat")
    service.clear_cache()

    await service.get_summary(profile)
    await service.get_summary(profile)

    miss, hit = _events(capture, "cache")
    assert miss["result"] == "miss"
    assert miss["handle"] == "octocat"
    assert miss["stale"] is False
    assert miss["ttl"] == get_settings().cache_ttl_seconds
    assert hit["result"] == "hit"
    assert hit["stale"] is False


async def test_cache_event_reports_a_rebuild_after_an_unreadable_entry(
    capture: pytest.LogCaptureFixture,
):
    # A shared cache can hold an entry written by a deploy with a different model
    # schema; a spike in "rebuild" means schema drift, not cold traffic.
    profile = ProfileInput(github="octocat")
    service.clear_cache()
    await service._cache_write(service._cache_key(profile), "not json at all", 60)
    capture.clear()

    await service.get_summary(profile)

    (event,) = _events(capture, "cache")
    assert event["result"] == "rebuild"


async def test_cache_event_reports_the_negative_ttl_for_a_degraded_build(
    capture: pytest.LogCaptureFixture, live_mode: None, monkeypatch: pytest.MonkeyPatch
):
    from codemaru.settings import get_settings

    async def dead_solvedac(handle: str, **_: Any) -> SolvedAcSnapshot:
        return SolvedAcSnapshot(
            status=PlatformStatus.UNAVAILABLE,
            fetched_at=_TS,
            handle=handle,
            tier=0,
            rating=0,
            solved_count=0,
            class_level=0,
        )

    monkeypatch.setattr(service, "fetch_github", _ok_github)
    monkeypatch.setattr(service, "fetch_solvedac", dead_solvedac)
    service.clear_cache()

    await service.get_summary(ProfileInput(github="octocat", boj="baek"))

    (event,) = _events(capture, "cache")
    assert event["ttl"] == get_settings().negative_cache_ttl_seconds


# --- kv_error events ---------------------------------------------------------


async def test_kv_error_event_on_a_failed_read(
    capture: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
):
    async def boom(*_args: str) -> object:
        raise TimeoutError("kv unreachable at https://kv.example?token=secret")

    monkeypatch.setattr("codemaru.kv.credentials", lambda: ("https://kv.example", "tok"))
    monkeypatch.setattr("codemaru.kv.command", boom)

    assert await service._cache_read("some-key") is None

    (event,) = _events(capture, "kv_error")
    assert event["op"] == "get"
    # Class name ONLY: a KV message can carry the credentialed REST URL.
    assert event["error"] == "TimeoutError"
    assert "secret" not in json.dumps(event)


async def test_kv_error_event_on_a_failed_write(
    capture: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
):
    async def boom(*_args: str) -> object:
        raise RuntimeError("nope")

    monkeypatch.setattr("codemaru.kv.credentials", lambda: ("https://kv.example", "tok"))
    monkeypatch.setattr("codemaru.kv.command", boom)

    await service._cache_write("some-key", "{}", 60)  # must not raise

    (event,) = _events(capture, "kv_error")
    assert event["op"] == "set"
    assert event["error"] == "RuntimeError"


async def test_kv_error_event_from_analytics(
    capture: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
):
    async def boom(*_args: str) -> object:
        raise ConnectionError("down")

    monkeypatch.setattr(analytics, "_credentials", lambda: ("https://kv.example", "tok"))
    monkeypatch.setattr(analytics, "_command", boom)
    analytics._seen.clear()

    await analytics.record_embed("octocat")  # best-effort: must not raise

    (event,) = _events(capture, "kv_error")
    assert event["op"] == "pfadd"
    assert event["error"] == "ConnectionError"


# --- route catch-all ---------------------------------------------------------


def test_card_route_catch_all_logs_the_handle_with_a_traceback(
    client: Any, capture: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
):
    # The viewer only sees "temporarily unavailable"; without this log the branch
    # would swallow real bugs.
    async def boom(profile: object) -> object:
        raise RuntimeError("something internal exploded")

    monkeypatch.setattr("codemaru.web.routes.get_summary", boom)
    capture.set_level(logging.ERROR, logger="codemaru")

    res = client.get("/api/card.svg", params={"github": "octocat"})
    assert res.status_code == 200

    record = next(r for r in capture.records if r.name == "codemaru")
    payload = json.loads(telemetry.JsonLineFormatter().format(record))
    assert payload["event"] == "card_error"
    assert payload["handle"] == "octocat"
    assert "something internal exploded" in payload["error"]
    # ...but the viewer's card never carries it.
    assert "something internal exploded" not in res.text
