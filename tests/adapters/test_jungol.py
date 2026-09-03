"""JungOl adapter: the devalue decoder, the pure parser, and the fetch paths.

Everything runs against payloads captured from jungol.co.kr on 2026-09-02 and
saved under ``fixtures/`` — the format is a SvelteKit internal, so a real
recording is the only honest regression guard. The single live test is marked
``integration`` and is excluded from the default run.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest

from codemaru.adapters.jungol import (
    account_url,
    decode_payload,
    fetch_jungol,
    handle_url,
    parse_account,
    unflatten,
)
from codemaru.core.normalization import linear_score
from codemaru.models.snapshot import PlatformStatus

_TS = datetime(2026, 5, 31, tzinfo=UTC)
_FIXTURES = Path(__file__).parent / "fixtures"

# jungol.co.kr/@jungol -> /account/42058: 70 solved problems spanning bronze
# through platinum, so the band mapping is exercised end to end.
_RANKED_ID = 42058
# jungol.co.kr/@hancom -> /account/152213: zero solves, and — the trap this
# adapter has to survive — no `rank`/`tier`/`rv` keys at all.
_UNRANKED_ID = 152213


def _fixture(name: str) -> Any:
    return json.loads((_FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


def _ranked() -> Any:
    return _fixture("jungol_account_42058")


def _unranked() -> Any:
    return _fixture("jungol_account_152213")


# The handle -> account-id step, as jungol.co.kr really answers it.
def _lookup_hit() -> Any:
    return _fixture("jungol_handle_redirect")  # /@jungol


def _lookup_unranked() -> Any:
    return _fixture("jungol_handle_unranked")  # /@hancom


def _lookup_miss() -> Any:
    return _fixture("jungol_handle_notfound")  # a handle nobody owns


# --- unflatten (the devalue decoder) -------------------------------------


def test_unflatten_resolves_index_references():
    # [0] is the root; every value in it is an index into the same array.
    assert unflatten([{"a": 1, "b": 2}, "hello", 42]) == {"a": "hello", "b": 42}


def test_unflatten_rebuilds_nested_lists_and_objects():
    flat = [{"items": 1}, [2, 3], {"id": 4}, {"id": 5}, 10, 20]
    assert unflatten(flat) == {"items": [{"id": 10}, {"id": 20}]}


def test_unflatten_shares_one_value_across_several_references():
    # The whole point of the format: a repeated value is stored once.
    assert unflatten([{"a": 1, "b": 1}, "same"]) == {"a": "same", "b": "same"}


def test_unflatten_maps_negative_sentinels_to_none():
    # -1 null, -2 undefined, -3..-6 NaN / Infinity / -Infinity / -0.
    decoded = unflatten([{"n": -1, "u": -2, "nan": -3, "inf": -4}])
    assert decoded == {"n": None, "u": None, "nan": None, "inf": None}


def test_unflatten_unwraps_tagged_values():
    assert unflatten([{"when": 1}, ["Date", "2026-09-02T00:00:00.000Z"]]) == {
        "when": "2026-09-02T00:00:00.000Z"
    }


def test_unflatten_survives_a_self_referencing_payload():
    # Containers are registered before being filled, so a cycle terminates.
    decoded = unflatten([{"self": 0}])
    assert isinstance(decoded, dict)
    assert decoded["self"] is decoded


def test_unflatten_ignores_out_of_range_and_non_integer_references():
    assert unflatten([{"gone": 99, "weird": "nope"}]) == {"gone": None, "weird": None}


@pytest.mark.parametrize("bad", [None, [], {}, "text", 0])
def test_unflatten_rejects_anything_that_is_not_a_devalue_array(bad: object):
    assert unflatten(bad) is None


def test_decode_payload_merges_every_data_node():
    decoded = decode_payload(_ranked())
    assert f"$/account/{_RANKED_ID}" in decoded
    assert f"$/account/{_RANKED_ID}/stat" in decoded


@pytest.mark.parametrize(
    "payload",
    [None, [], {}, {"nodes": None}, {"nodes": [None, {"type": "skip"}]}],
    ids=["none", "list", "empty", "nodes-null", "no-data-nodes"],
)
def test_decode_payload_tolerates_a_payload_with_no_data(payload: object):
    assert decode_payload(payload) == {}


# --- parse_account -------------------------------------------------------


def test_parse_account_reads_a_ranked_profile():
    snap = parse_account(decode_payload(_ranked()), "jungol", _TS)
    assert snap.status is PlatformStatus.OK
    assert snap.handle == "jungol"
    assert snap.account_id == _RANKED_ID
    assert snap.tier == 7  # Silver IV on the solved.ac scale
    assert snap.rating == 340  # the payload's `rv`
    assert snap.rank == 4791
    assert snap.solved_count == 70
    assert snap.note is None


def test_parse_account_buckets_solved_problems_into_difficulty_bands():
    snap = parse_account(decode_payload(_ranked()), "jungol", _TS)
    d = snap.difficulty
    assert (d.bronze, d.silver, d.gold, d.platinum, d.diamond, d.ruby) == (15, 14, 11, 1, 0, 0)
    # Tier-0 (Unrated) problems are ignored, exactly as in solved.ac's mapping,
    # so the bands sum to less than the solved count.
    assert d.bronze + d.silver + d.gold + d.platinum < snap.solved_count


def test_parse_account_handles_an_unranked_account():
    # `rank` / `tier` / `rv` are ABSENT here, not zero. Reading the profile node
    # by `rank` instead of `handle` would drop this account entirely.
    snap = parse_account(decode_payload(_unranked()), "hancom", _TS)
    assert snap.status is PlatformStatus.OK
    assert snap.handle == "hancom"
    assert snap.account_id == _UNRANKED_ID
    assert (snap.tier, snap.rating, snap.rank, snap.solved_count) == (0, 0, 0, 0)


def test_unranked_fixture_really_omits_the_rank_keys():
    # Guards the assumption the parser is built on: if a future capture starts
    # including these keys, the test above stops proving anything.
    node = decode_payload(_unranked())[f"$/account/{_UNRANKED_ID}"]["data"]
    assert "handle" in node
    assert not {"rank", "tier", "rv"} & set(node)


def test_parse_account_ignores_the_logged_out_my_account_node():
    # `$/account/my` shares the prefix but holds a logged-out 401 error with no
    # `data` key at all, so matching on the prefix alone would pick it up.
    decoded = decode_payload(_ranked())
    my = decoded["$/account/my"]
    assert my["code"] == 401 and "data" not in my
    snap = parse_account(decoded, "jungol", _TS)
    assert snap.handle == "jungol"
    assert snap.account_id == _RANKED_ID


def test_parse_account_prefers_the_payload_handle_over_the_requested_one():
    snap = parse_account(decode_payload(_ranked()), "JUNGOL", _TS)
    assert snap.handle == "jungol"


def test_parse_account_without_a_profile_node_is_unavailable():
    snap = parse_account({"$/account/my": {"data": None}}, "ghost", _TS)
    assert snap.status is PlatformStatus.UNAVAILABLE
    assert snap.note == "unexpected response"
    assert snap.handle == "ghost"


def test_parse_account_without_a_stat_node_is_partial():
    # Solve counts come only from the history, so a missing stat node must read
    # as "unknown", not "solved nothing" — the same rule solved.ac follows.
    decoded = decode_payload(_ranked())
    del decoded[f"$/account/{_RANKED_ID}/stat"]
    snap = parse_account(decoded, "jungol", _TS)
    assert snap.status is PlatformStatus.PARTIAL
    assert snap.note == "solved history unavailable"
    assert snap.tier == 7  # profile metrics survive
    assert snap.solved_count == 0


def test_parse_account_clamps_and_defends_against_odd_field_types():
    decoded = {
        "$/account/1": {
            "data": {"handle": "odd", "id": "nope", "tier": 99, "rv": None, "rank": -5}
        },
        "$/account/1/stat": {"data": {"solved": "not-a-list"}},
    }
    snap = parse_account(decoded, "odd", _TS)
    assert (snap.account_id, snap.tier, snap.rating, snap.rank) == (0, 30, 0, 0)
    assert snap.solved_count == 0


def test_parse_account_skips_malformed_solved_entries():
    decoded = {
        "$/account/1": {"data": {"handle": "odd", "id": 1}},
        "$/account/1/stat": {
            "data": {
                "solved": [
                    {"id": 1, "tier": {"tier": 12}},  # gold
                    {"id": 2, "tier": None},  # no tier -> unrated, ignored
                    {"id": 3},  # no tier key at all
                    "not-a-dict",  # dropped entirely
                ]
            }
        },
    }
    snap = parse_account(decoded, "odd", _TS)
    # Every well-formed entry counts toward solved_count; only tiered ones band.
    assert snap.solved_count == 4
    assert snap.difficulty.gold == 1


# --- judge_view ----------------------------------------------------------


def solvedac_evidence(tier: int) -> float:
    """What solved.ac would report for the same tier — the unscaled signal."""
    return linear_score(tier, 30)


def test_judge_view_scales_the_rating_evidence_down():
    snap = parse_account(decode_payload(_ranked()), "jungol", _TS)
    view = snap.judge_view()
    assert view.platform == "jungol"
    assert view.handle == "jungol"
    assert view.solved_count == 70
    # linear_score(7, 30) * 0.80 — JungOl's smaller problem pool makes the same
    # tier weaker evidence than solved.ac's. (linear_score rounds to 1 decimal,
    # so the tier term is 23.3, not 23.33…)
    assert view.rating_evidence == pytest.approx(23.3 * 0.80)
    assert view.rating_evidence < solvedac_evidence(tier=7)
    # Same hard-volume weights as solved.ac (gold*0.3 + platinum*1 + ...).
    assert view.hard_volume == pytest.approx(11 * 0.3 + 1)


# --- fetch_jungol --------------------------------------------------------


def _client(handler: Any) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _routes(
    *, lookup: httpx.Response, account: httpx.Response | None = None
) -> tuple[Any, list[str]]:
    """A handler serving the two-step lookup, plus the URLs it was asked for."""
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        if request.url.path.startswith("/@"):
            return lookup
        assert account is not None, "the account URL should not have been requested"
        return account

    return handler, seen


def _json(payload: Any, status: int = 200) -> httpx.Response:
    return httpx.Response(status, json=payload)


async def test_fetch_jungol_ok_makes_exactly_two_requests():
    # Both responses are the real captured payloads, so this is the full live
    # round trip minus the network.
    handler, seen = _routes(lookup=_json(_lookup_hit()), account=_json(_ranked()))
    async with _client(handler) as client:
        snap = await fetch_jungol("jungol", fetched_at=_TS, client=client)

    assert snap.status is PlatformStatus.OK
    assert snap.solved_count == 70
    assert seen == [handle_url("jungol"), account_url(_RANKED_ID)]


async def test_fetch_jungol_user_not_found_is_unavailable():
    # A handle nobody owns redirects to the site root instead of an account.
    assert _lookup_miss()["location"] == "./"
    handler, seen = _routes(lookup=_json(_lookup_miss()))
    async with _client(handler) as client:
        snap = await fetch_jungol("ghost", fetched_at=_TS, client=client)

    assert snap.status is PlatformStatus.UNAVAILABLE
    assert snap.note == "user not found"
    assert len(seen) == 1  # no account request is attempted


async def test_fetch_jungol_resolves_an_unranked_account_end_to_end():
    # The account with no rank/tier/rv keys, driven through both real payloads:
    # it must come back `ok` and empty, never `unavailable`.
    handler, seen = _routes(lookup=_json(_lookup_unranked()), account=_json(_unranked()))
    async with _client(handler) as client:
        snap = await fetch_jungol("hancom", fetched_at=_TS, client=client)

    assert snap.status is PlatformStatus.OK
    assert snap.handle == "hancom"
    assert (snap.tier, snap.rating, snap.rank, snap.solved_count) == (0, 0, 0, 0)
    assert seen == [handle_url("hancom"), account_url(_UNRANKED_ID)]


async def test_fetch_jungol_quotes_the_handle_into_the_path():
    handler, seen = _routes(lookup=_json(_lookup_miss()))
    async with _client(handler) as client:
        await fetch_jungol("a/b", fetched_at=_TS, client=client)

    # The handle goes into a URL *path*, so it must not be able to reshape it.
    assert seen == ["https://jungol.co.kr/@a%2Fb/__data.json"]


async def test_fetch_jungol_http_error_on_the_lookup_is_unavailable():
    handler, _seen = _routes(lookup=_json({"error": "nope"}, status=500))
    async with _client(handler) as client:
        snap = await fetch_jungol("jungol", fetched_at=_TS, client=client)

    assert snap.status is PlatformStatus.UNAVAILABLE
    assert snap.note == "http 500"


async def test_fetch_jungol_http_error_on_the_account_is_unavailable():
    handler, _seen = _routes(
        lookup=_json({"type": "redirect", "location": f"./account/{_RANKED_ID}"}),
        account=_json({"detail": "계정이 없어요."}, status=404),
    )
    async with _client(handler) as client:
        snap = await fetch_jungol("jungol", fetched_at=_TS, client=client)

    assert snap.status is PlatformStatus.UNAVAILABLE
    assert snap.note == "http 404"


@pytest.mark.parametrize(
    "lookup_body",
    [{"type": "redirect"}, {"location": 42}, ["not", "a", "dict"], "plain text"],
    ids=["no-location", "location-not-a-string", "list", "string"],
)
async def test_fetch_jungol_unusable_lookup_payload_is_unavailable(lookup_body: Any):
    handler, _seen = _routes(lookup=_json(lookup_body))
    async with _client(handler) as client:
        snap = await fetch_jungol("jungol", fetched_at=_TS, client=client)

    assert snap.status is PlatformStatus.UNAVAILABLE
    assert snap.note == "user not found"


async def test_fetch_jungol_invalid_json_is_unavailable():
    handler, _seen = _routes(lookup=httpx.Response(200, content=b"<html>nope</html>"))
    async with _client(handler) as client:
        snap = await fetch_jungol("jungol", fetched_at=_TS, client=client)

    assert snap.status is PlatformStatus.UNAVAILABLE
    assert snap.note == "request failed"


async def test_fetch_jungol_schema_drift_in_the_account_payload_is_unavailable():
    # Valid JSON, but nothing that looks like an account node any more.
    handler, _seen = _routes(
        lookup=_json({"type": "redirect", "location": f"./account/{_RANKED_ID}"}),
        account=_json({"type": "data", "nodes": [{"type": "data", "data": [{"other": 1}, "x"]}]}),
    )
    async with _client(handler) as client:
        snap = await fetch_jungol("jungol", fetched_at=_TS, client=client)

    assert snap.status is PlatformStatus.UNAVAILABLE
    assert snap.note == "unexpected response"


async def test_fetch_jungol_oversized_body_is_rejected_before_parsing():
    # The solved history scales with the account, so the body is the one
    # unbounded input; past the guard it must not even be decoded.
    huge = httpx.Response(200, content=b"x" * (4 * 1024 * 1024 + 1))
    handler, seen = _routes(
        lookup=_json({"type": "redirect", "location": f"./account/{_RANKED_ID}"}),
        account=huge,
    )
    async with _client(handler) as client:
        snap = await fetch_jungol("jungol", fetched_at=_TS, client=client)

    assert snap.status is PlatformStatus.UNAVAILABLE
    assert snap.note == "response too large"
    assert len(seen) == 2


async def test_fetch_jungol_timeout_is_unavailable():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("too slow", request=request)

    async with _client(handler) as client:
        snap = await fetch_jungol("jungol", fetched_at=_TS, client=client)

    assert snap.status is PlatformStatus.UNAVAILABLE
    assert snap.note == "request failed"
    assert snap.handle == "jungol"


async def test_fetch_jungol_connect_error_is_unavailable():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom", request=request)

    async with _client(handler) as client:
        snap = await fetch_jungol("jungol", fetched_at=_TS, client=client)

    assert snap.status is PlatformStatus.UNAVAILABLE


async def test_fetch_jungol_logs_one_adapter_line(monkeypatch: pytest.MonkeyPatch):
    logged: list[dict[str, Any]] = []

    def spy(event: str, **fields: Any) -> None:
        logged.append({"event": event, **fields})

    monkeypatch.setattr("codemaru.telemetry.log_event", spy)
    handler, _seen = _routes(lookup=_json(_lookup_miss()))
    async with _client(handler) as client:
        await fetch_jungol("ghost", fetched_at=_TS, client=client)

    assert [entry["platform"] for entry in logged] == ["jungol"]
    assert logged[0]["status"] is PlatformStatus.UNAVAILABLE
    assert logged[0]["handle"] == "ghost"


# --- live -----------------------------------------------------------------


@pytest.mark.integration
async def test_fetch_jungol_live():
    """Resolve a real handle against jungol.co.kr (opt-in, excluded from CI).

    The payload is an internal SvelteKit format that can change without notice,
    so this is the check that says whether the saved fixtures still describe the
    live site.
    """
    from codemaru.adapters.base import build_client

    async with build_client(10.0) as client:
        snap = await fetch_jungol("jungol", fetched_at=datetime.now(UTC), client=client)

    assert snap.status is PlatformStatus.OK
    assert snap.handle == "jungol"
    assert snap.account_id == _RANKED_ID
    assert snap.solved_count > 0
    assert 0 <= snap.tier <= 30
