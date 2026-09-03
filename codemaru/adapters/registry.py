"""The judge-platform registry — one row per competitive-programming judge.

Every judge-specific *constant* that used to be scattered as a named parameter
across scoring, confidence, the summary builder, the service, the CLI and the
generator lives here instead: scoring, confidence and summary assembly all walk
``JUDGES`` and need no edit when a row is added.

The registry is not, however, the only place a new judge touches. Adding one
means, in order:

1. a row here (appended — reordering changes cache keys and generated URLs);
2. an adapter module in ``codemaru/adapters/`` plus its export in
   ``adapters/__init__.py``, and a snapshot model + ``SnapshotBundle`` field
   named exactly like the row's ``key``;
3. ``service._judge_fetchers()`` and ``service._JUDGE_UNAVAILABLE`` — a key
   missing from the first is silently never fetched; missing from the second it
   raises the moment the card-build budget cuts that judge short;
4. the public query contract: ``web/query.parse_request`` (its ``supplied``
   dict and signature) and the query parameters of ``/api/card.svg``,
   ``/api/summary.json`` and ``/`` in ``web/routes.py``;
5. the other front doors: ``cli.py``, ``action.yml``, ``templates/index.html``
   and ``static/generator.js``;
6. ``fixtures/demo.py`` (a fixture snapshot and a handle on ``DEMO_INPUT``), and
   the docs — ``README*.md``, ``docs/SCORING.md``, ``CHANGELOG.md``.

Steps 3 and 4 are covered by completeness tests in
``tests/adapters/test_registry.py`` and ``tests/api/test_build_budget.py``, which
fail for a judge that was added to the registry but not wired up.

Deliberately dependency-free: this module imports nothing from codemaru, and in
particular holds no ``fetch`` callables. The adapters import
``codemaru.models``, so a registry that referenced them would close an import
cycle for every consumer. The ``key -> fetch`` dispatch map lives in
``codemaru.service`` instead, next to the code that actually schedules them.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class JudgePlatform:
    """Everything the rest of the codebase needs to know about one judge."""

    # Snapshot/bundle field name — ``SnapshotBundle.<key>`` and the wire key
    # under ``snapshots`` in /api/summary.json.
    key: str
    # Query / CLI / Action input name. Differs from ``key`` where the public
    # contract predates the registry (solved.ac is requested as ``boj``).
    param: str
    # Human-readable label for UI surfaces.
    label: str
    # How much this judge's data is believed, 0-1 (see core/confidence.py).
    trust: float
    # Solved-count at which the confidence volume curve saturates.
    saturation: float
    # Additive confidence weight. Weights are NOT renormalized when a judge is
    # added — that would lower existing users' confidence — the existing clamp
    # to [0, 1] absorbs any overshoot.
    weight: float
    # Whether the adapter uses the shared httpx client. solved.ac needs its own
    # curl_cffi session (Cloudflare rejects plain-Python TLS fingerprints).
    shared_client: bool


# Registry order is the canonical order everywhere: judge iteration, the cache
# key's handle segment, query-string params, and the Action snippet. Appending a
# row is safe; reordering changes cache keys and generated URLs.
JUDGES: tuple[JudgePlatform, ...] = (
    JudgePlatform(
        key="solvedac",
        param="boj",
        label="BOJ / solved.ac",
        trust=1.00,
        saturation=2200,
        weight=0.25,
        shared_client=False,
    ),
    JudgePlatform(
        key="leetcode",
        param="leetcode",
        label="LeetCode",
        trust=0.75,
        saturation=1400,
        weight=0.15,
        shared_client=True,
    ),
    JudgePlatform(
        key="jungol",
        param="jungol",
        label="JungOl / 정올",
        # Lower trust than solved.ac: the data comes from a SvelteKit internal
        # payload rather than a documented API. The saturation is scaled to
        # JungOl's much smaller problem pool (~2,600 problems).
        trust=0.60,
        saturation=900,
        weight=0.10,
        shared_client=True,
    ),
)


def judge_by_key(key: str) -> JudgePlatform | None:
    """Look a judge up by its snapshot/bundle field name."""
    for platform in JUDGES:
        if platform.key == key:
            return platform
    return None


def judge_by_param(param: str) -> JudgePlatform | None:
    """Look a judge up by its query / CLI / Action input name."""
    for platform in JUDGES:
        if platform.param == param:
            return platform
    return None
