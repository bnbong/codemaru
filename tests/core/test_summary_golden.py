"""Golden digest of the demo-fixture summary — the wire contract, pinned.

``tests/render/golden.py`` pins what a card *looks* like; this pins what the API
*says*. ``build_summary`` is pure and the demo fixture is a set of constants at a
fixed timestamp, so ``/api/summary.json``'s payload for it is byte-deterministic
— which makes a hash a total regression guard over scoring, confidence, tier
assignment, metric selection and every field alias at once.

Its job is to make "no behaviour change" checkable rather than asserted: a
refactor that claims to preserve output either leaves this digest alone or it
did not preserve output. The companions are the two constants pinned as literals
below — ``SCORE_VERSION`` and the cache-key format — because a formula change
that forgets to bump the version silently serves old and new scores from the same
cache entry.

After an *intentional* change, review the payload diff, bump ``SCORE_VERSION`` if
a formula moved, and then refresh the digest with::

    uv run python -m tests.core.test_summary_golden --update
"""

from __future__ import annotations

import hashlib
import re
import sys
from pathlib import Path

import pytest

from codemaru import service
from codemaru.core.scoring import SCORE_VERSION
from codemaru.core.summary import build_summary
from codemaru.fixtures.demo import DEMO_INPUT, FIXED_TIMESTAMP, full_bundle
from codemaru.settings import get_settings

UPDATE_COMMAND = "uv run python -m tests.core.test_summary_golden --update"

# --- begin golden digest ---
GOLDEN_DIGEST = "cf755968db672426df6e1336551078c642f387b2c43a129e9c0f64af5699b411"
# --- end golden digest ---


def summary_json() -> str:
    """The public JSON payload for the demo profile, exactly as the route emits it.

    ``by_alias=True`` matters: the aliases *are* the wire contract, so a renamed
    field has to move the digest.
    """
    summary = build_summary(DEMO_INPUT, full_bundle(), FIXED_TIMESTAMP)
    return summary.model_dump_json(by_alias=True)


def digest() -> str:
    """SHA-256 of that payload."""
    return hashlib.sha256(summary_json().encode("utf-8")).hexdigest()


def test_demo_summary_matches_the_golden_digest():
    actual = digest()
    assert actual == GOLDEN_DIGEST, (
        f"the demo summary payload changed: {GOLDEN_DIGEST} -> {actual}.\n"
        "build_summary is deterministic over the demo fixture, so this is a real "
        "change to what /api/summary.json returns — a scoring formula, a tier "
        "boundary, a metric, or a field alias. If it was intentional, review the "
        "payload diff, bump SCORE_VERSION if a formula moved, and then refresh "
        f"the digest with: {UPDATE_COMMAND}"
    )


def test_score_version_is_pinned():
    # A literal, not an import comparison: the digest above only catches an output
    # change, and bumping the version is what stops a shared cache from serving
    # summaries scored by the previous engine (SCORE_VERSION is a cache-key
    # segment). Changing a formula without changing this line has to fail here.
    assert SCORE_VERSION == "0.4.0"


def test_cache_key_format_for_a_full_profile(monkeypatch: pytest.MonkeyPatch):
    # Every segment earns its place: the score version (a formula change must not
    # reuse old entries), the deploy environment (a preview deploy must not
    # pollute production), the mode (fixture and live data must never share an
    # entry), and one segment per judge in registry order — always emitted, so two
    # different profiles cannot collapse onto the same key.
    monkeypatch.setenv("VERCEL_ENV", "local")
    monkeypatch.setenv("FIXTURE_MODE", "true")
    get_settings.cache_clear()

    assert service._cache_key(DEMO_INPUT) == (
        "summary:v0.4.0:local:fixture:codemaru-demo|codemaru_demo|codemaru_demo|codemaru_demo"
    )


def _update() -> int:
    """Rewrite the pinned digest in this file from a fresh build."""
    path = Path(__file__)
    new = re.sub(
        r"(# --- begin golden digest ---\n).*?(# --- end golden digest ---\n)",
        lambda m: m.group(1) + f'GOLDEN_DIGEST = "{digest()}"\n' + m.group(2),
        path.read_text(encoding="utf-8"),
        flags=re.DOTALL,
    )
    path.write_text(new, encoding="utf-8")
    print(f"updated the golden summary digest in {path}")
    return 0


if __name__ == "__main__":
    if sys.argv[1:] != ["--update"]:
        print(f"usage: {UPDATE_COMMAND}", file=sys.stderr)
        raise SystemExit(2)
    raise SystemExit(_update())
