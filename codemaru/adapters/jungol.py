"""JungOl (정올, jungol.co.kr) adapter — public SvelteKit page data.

JungOl publishes no API, but its account pages are server-rendered by SvelteKit,
which exposes the same data it hydrates the page with at ``<route>/__data.json``.
Two sequential GETs are enough:

1. ``/@<handle>/__data.json`` answers ``{"type":"redirect","location":"./account/<id>"}``
   — the handle → account-id lookup. A handle nobody owns answers ``"./"``.
2. ``/account/<id>/__data.json`` carries the profile and the solved history.

Unlike solved.ac, JungOl's Cloudflare setup is passive: plain ``httpx`` with
codemaru's own User-Agent gets a 200, so this adapter uses the shared client and
needs no browser TLS impersonation.

Two properties of the payload shape the code below.

**It is devalue-encoded.** SvelteKit flattens the data into an array where every
value is an *index* into that same array (which is how it can encode cycles and
shared references). ``unflatten`` walks it back into ordinary Python data — about
thirty lines, and the reason this adapter needs no HTML parser or extra
dependency.

**It is an internal framework format, not a contract.** A SvelteKit upgrade or a
move to client-side rendering could change or remove it without notice. So the
decoder and ``parse_account`` are pure functions tested against saved payloads,
every field is read with ``.get()``, and any failure — HTTP, timeout, schema
drift, an oversized body — degrades to ``unavailable`` rather than raising.

Tiers are the solved.ac 0..30 scale: JungOl's own account page states that a
tier is computed from the solved.ac AC rating, so ``adapters/tiers.py`` and
``core.format.solvedac_tier_name`` apply unchanged.
"""

from __future__ import annotations

from datetime import datetime
from time import monotonic
from typing import Any
from urllib.parse import quote

import httpx

from codemaru.adapters.tiers import parse_difficulty
from codemaru.models.snapshot import JungOlSnapshot, PlatformStatus
from codemaru.telemetry import log_adapter

BASE_URL = "https://jungol.co.kr"

# The solved history grows with the account, so the account payload is the only
# unbounded one. 4 MB is far past the observed worst case (a 70-problem account
# is 13 KB; extrapolating to 3,000 problems gives roughly 210 KB uncompressed),
# and stops a pathological or hostile response from being parsed at all.
_MAX_BODY_BYTES = 4 * 1024 * 1024

# Node keys in the decoded payload. ``$/account/my`` is the *viewer's* account —
# a 401 error object, since we are not logged in — and must not be mistaken for
# the profile being read.
_ACCOUNT_PREFIX = "$/account/"
_STAT_SUFFIX = "/stat"

__all__ = [
    "BASE_URL",
    "account_url",
    "decode_payload",
    "fetch_jungol",
    "handle_url",
    "parse_account",
    "unavailable_snapshot",
    "unflatten",
]


def handle_url(handle: str) -> str:
    """The handle → account-id lookup URL for ``handle``."""
    # Handles are validated upstream (``PLATFORM_RE``), but this one goes into a
    # path rather than a query value, so quote it anyway: a caller that skips
    # validation (the CLI, a future entry point) can't reshape the URL.
    return f"{BASE_URL}/@{quote(handle, safe='')}/__data.json"


def account_url(account_id: int) -> str:
    """The account-data URL for a resolved numeric account id."""
    return f"{BASE_URL}/account/{account_id}/__data.json"


def unavailable_snapshot(handle: str, note: str, fetched_at: datetime) -> JungOlSnapshot:
    """An all-zero snapshot standing in for data this platform could not supply.

    Public so the service layer can substitute one when the card-build budget
    cuts a fetch short, without duplicating the field list."""
    return JungOlSnapshot(
        status=PlatformStatus.UNAVAILABLE,
        fetched_at=fetched_at,
        note=note,
        handle=handle,
        account_id=0,
        tier=0,
        rating=0,
        rank=0,
        solved_count=0,
    )


def unflatten(flattened: object) -> object:
    """Rehydrate one SvelteKit *devalue* array into ordinary Python data.

    ``flattened[0]`` is the root; every other value is reached by index. A list
    of numbers is a list of index references, a dict maps keys to index
    references, and anything else is a literal. Negative indices are devalue's
    sentinels (-1 null, -2 undefined, -3..-6 NaN / Infinity / -Infinity / -0);
    all of them decode to ``None``, which is what the ``.get()``-everywhere
    parsing below already expects.

    Containers are registered in ``hydrated`` *before* being filled, so a payload
    that references itself terminates instead of recursing forever.
    """
    if not isinstance(flattened, list) or not flattened:
        return None
    hydrated: dict[int, object] = {}

    def hydrate(index: object) -> object:
        if not isinstance(index, int) or isinstance(index, bool):
            return None
        if index < 0 or index >= len(flattened):
            return None
        if index in hydrated:
            return hydrated[index]

        value = flattened[index]
        if isinstance(value, list):
            # A leading string marks a tagged value — ["Date", "..."],
            # ["BigInt", "..."], ["Set", ...]. Only the payload is kept; codemaru
            # reads none of these types, and unwrapping keeps the decoder small.
            if value and isinstance(value[0], str):
                tagged = value[1] if len(value) > 1 else None
                hydrated[index] = tagged
                return tagged
            items: list[object] = []
            hydrated[index] = items
            items.extend(hydrate(i) for i in value)
            return items
        if isinstance(value, dict):
            obj: dict[str, object] = {}
            hydrated[index] = obj
            for key, ref in value.items():
                obj[str(key)] = hydrate(ref)
            return obj
        hydrated[index] = value
        return value

    return hydrate(0)


def decode_payload(payload: object) -> dict[str, Any]:
    """Decode every data node of a ``__data.json`` response into one mapping.

    SvelteKit ships one node per layout level, each separately flattened. Their
    decoded roots are disjoint key spaces, so merging them gives a single mapping
    keyed by route (``$/account/42058``, ``$/account/42058/stat``, ...).
    """
    if not isinstance(payload, dict):
        return {}
    nodes = payload.get("nodes")
    merged: dict[str, Any] = {}
    if not isinstance(nodes, list):
        return merged
    for node in nodes:
        if not isinstance(node, dict) or node.get("type") != "data":
            continue
        decoded = unflatten(node.get("data"))
        if isinstance(decoded, dict):
            merged.update(decoded)
    return merged


def _account_nodes(decoded: dict[str, Any]) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Pick the profile and solved-history nodes out of a decoded payload.

    The profile is identified by its ``handle`` key, never by ``rank``: an
    account that has solved nothing carries no ``rank``/``tier``/``rv`` at all
    (the keys are absent, not zero), and matching on those would drop it.
    """
    account: dict[str, Any] | None = None
    stat: dict[str, Any] | None = None
    for key, node in decoded.items():
        if not key.startswith(_ACCOUNT_PREFIX) or not isinstance(node, dict):
            continue
        data = node.get("data")
        if not isinstance(data, dict):
            # ``$/account/my`` is a 401 error object while logged out.
            continue
        if key.endswith(_STAT_SUFFIX):
            stat = data
        elif "handle" in data:
            account = data
    return account, stat


def _int_field(source: dict[str, Any], key: str, *, maximum: int | None = None) -> int:
    """Read a non-negative int, treating a missing/odd value as 0.

    Absent keys are normal here (unranked accounts), and the payload is an
    undocumented internal format, so a wrong type degrades to 0 rather than
    failing the whole snapshot.
    """
    try:
        value = int(source.get(key) or 0)
    except (TypeError, ValueError):
        return 0
    value = max(0, value)
    return min(value, maximum) if maximum is not None else value


def _difficulty_stats(solved: list[Any]) -> list[dict[str, Any]]:
    """Reshape the solved list into the ``{level, solved}`` rows tiers.py takes.

    Each solved entry carries its problem's own tier on the solved.ac 0..30
    scale, so one row per problem lets the shared band table do the counting.
    """
    rows: list[dict[str, Any]] = []
    for problem in solved:
        if not isinstance(problem, dict):
            continue
        tier = problem.get("tier")
        level = tier.get("tier") if isinstance(tier, dict) else None
        try:
            rows.append({"level": int(level or 0), "solved": 1})
        except (TypeError, ValueError):
            continue
    return rows


def parse_account(
    decoded: dict[str, Any],
    handle: str,
    fetched_at: datetime,
) -> JungOlSnapshot:
    """Build a JungOlSnapshot from a decoded ``/account/<id>/__data.json`` payload.

    A payload with no recognizable profile node is schema drift, so it maps to
    ``unavailable``. A profile without its ``stat`` sibling is ``partial``: the
    tier and rating survive, but the solved count comes from the history alone,
    so its absence must not read as "solved nothing".
    """
    account, stat = _account_nodes(decoded)
    if account is None:
        return unavailable_snapshot(handle, "unexpected response", fetched_at)

    raw_handle = account.get("handle")
    solved = stat.get("solved") if stat is not None else None
    if not isinstance(solved, list):
        solved = []

    partial = stat is None
    return JungOlSnapshot(
        status=PlatformStatus.PARTIAL if partial else PlatformStatus.OK,
        fetched_at=fetched_at,
        note="solved history unavailable" if partial else None,
        handle=raw_handle if isinstance(raw_handle, str) and raw_handle else handle,
        account_id=_int_field(account, "id"),
        tier=_int_field(account, "tier", maximum=30),
        # JungOl names the AC rating "rv".
        rating=_int_field(account, "rv"),
        rank=_int_field(account, "rank"),
        # There is no solved-count field; the history length is the count.
        solved_count=len(solved),
        difficulty=parse_difficulty(_difficulty_stats(solved)),
    )


async def fetch_jungol(
    handle: str,
    *,
    fetched_at: datetime,
    client: httpx.AsyncClient,
) -> JungOlSnapshot:
    """Fetch a JungOl snapshot, mapping any failure to ``unavailable``."""
    # A thin wrapper around the real fetch so every exit path — ok, partial,
    # unavailable — is logged from one place.
    started = monotonic()
    snapshot = await _fetch_jungol(handle, fetched_at=fetched_at, client=client)
    log_adapter("jungol", handle, status=snapshot.status, note=snapshot.note, started=started)
    return snapshot


def _resolve_account_id(payload: object) -> int | None:
    """Read the account id out of the handle-lookup redirect payload.

    ``{"location": "./account/42058"}`` for a real handle; ``"./"`` for one that
    doesn't exist, which yields ``None``.
    """
    if not isinstance(payload, dict):
        return None
    location = payload.get("location")
    if not isinstance(location, str):
        return None
    tail = location.rstrip("/").rsplit("/", 1)[-1]
    return int(tail) if tail.isdigit() else None


async def _fetch_jungol(
    handle: str,
    *,
    fetched_at: datetime,
    client: httpx.AsyncClient,
) -> JungOlSnapshot:
    try:
        lookup = await client.get(handle_url(handle))
        if lookup.status_code != 200:
            return unavailable_snapshot(handle, f"http {lookup.status_code}", fetched_at)
        if len(lookup.content) > _MAX_BODY_BYTES:
            return unavailable_snapshot(handle, "response too large", fetched_at)

        account_id = _resolve_account_id(lookup.json())
        if account_id is None:
            return unavailable_snapshot(handle, "user not found", fetched_at)

        # Sequential by necessity: the second URL is built from the first answer.
        account = await client.get(account_url(account_id))
        if account.status_code != 200:
            return unavailable_snapshot(handle, f"http {account.status_code}", fetched_at)
        # The solved history is proportional to the account's size, so this is
        # the response that could in principle be huge.
        if len(account.content) > _MAX_BODY_BYTES:
            return unavailable_snapshot(handle, "response too large", fetched_at)

        return parse_account(decode_payload(account.json()), handle, fetched_at)
    except Exception:  # noqa: BLE001 - degrade gracefully on any network/schema error
        return unavailable_snapshot(handle, "request failed", fetched_at)
