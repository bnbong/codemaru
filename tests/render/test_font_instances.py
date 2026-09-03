"""The two-tier font loading in codemaru.render.glyphs.

Instancing a variable font costs ~200 ms per weight, so every weight the card
uses ships pre-instanced (``scripts/instance_fonts.py``) and the renderer must
never fall back to instancing on a cold serverless start.
"""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

from codemaru.render import glyphs
from codemaru.render.glyphs import MONO, SANS, STATIC_INSTANCES
from tests.render.golden import GOLDEN, UPDATE_COMMAND, digests, render_variants

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = _REPO_ROOT / "scripts" / "instance_fonts.py"


@pytest.fixture
def cold_fonts() -> Iterator[None]:
    """Empty the font caches so a test observes the real first-load path."""
    glyphs._instance.cache_clear()
    glyphs._glyph.cache_clear()
    yield
    glyphs._instance.cache_clear()
    glyphs._glyph.cache_clear()


def test_every_renderer_weight_ships_a_static_instance():
    for family, weight in STATIC_INSTANCES:
        path = glyphs.static_path(family, weight)
        assert path.is_file(), f"missing {path.name} — run: uv run python scripts/instance_fonts.py"
        assert path.stat().st_size > 0


def test_rendering_all_variants_never_instances_at_runtime(cold_fonts, monkeypatch):
    # Renders go through the pre-instanced static TTFs only; a hit here means a
    # weight was added to card.py/icons.py without being added to STATIC_INSTANCES.
    def fail(family: str, weight: int) -> None:
        raise AssertionError(
            f"({family}, {weight}) was instanced at render time — add it to "
            "STATIC_INSTANCES and run: uv run python scripts/instance_fonts.py"
        )

    monkeypatch.setattr(glyphs, "_load_instanced", fail)
    for name, svg in render_variants().items():
        assert svg.startswith("<svg"), name


def test_static_instances_cover_exactly_the_weights_the_renderer_asks_for(cold_fonts, monkeypatch):
    seen: set[tuple[str, int]] = set()
    real = glyphs._load_static

    def spy(family: str, weight: int):
        seen.add((family, weight))
        return real(family, weight)

    monkeypatch.setattr(glyphs, "_load_static", spy)
    render_variants()
    # Nothing shipped is dead weight, and nothing asked for is missing.
    assert seen == set(STATIC_INSTANCES)


def test_unexpected_weight_falls_back_to_instancing(cold_fonts, monkeypatch):
    # 450 is inside Space Grotesk's wght axis but nobody pre-instanced it.
    assert not glyphs.static_path(SANS, 450).is_file()
    calls: list[tuple[str, int]] = []
    real = glyphs._load_instanced

    def spy(family: str, weight: int):
        calls.append((family, weight))
        return real(family, weight)

    monkeypatch.setattr(glyphs, "_load_instanced", spy)
    out = glyphs.text_path("Ag", family=SANS, weight=450, size=12, x=0, y=10, fill="#000")
    assert calls == [(SANS, 450)]
    assert '<path transform="translate(0 0)" d="M' in out  # real outlines, not blanks
    assert glyphs.text_width("Ag", family=SANS, weight=450, size=12) > 0


def test_out_of_range_weight_clamps_onto_a_shipped_instance(cold_fonts):
    # 900 is above Space Grotesk's max (700), which *is* shipped: the clamped
    # weight reuses the static file rather than instancing a second copy of 700.
    heavy = glyphs.text_path("A", family=SANS, weight=900, size=12, x=0, y=10, fill="#000")
    at_max = glyphs.text_path("A", family=SANS, weight=700, size=12, x=0, y=10, fill="#000")
    assert heavy == at_max


@pytest.mark.parametrize(("family", "weight"), [(SANS, 500), (MONO, 600)])
def test_static_file_and_live_instancing_agree_on_metrics(cold_fonts, family, weight):
    # Saving a TTF rounds outline coordinates to integers (glyf stores int16), so
    # the two tiers' path data can differ by up to half a font unit. Everything
    # that positions text — upm, cmap, advances — must match exactly, or the two
    # tiers would lay text out differently.
    static = glyphs._load_static(family, weight)
    assert static is not None
    static_upm, static_glyphs, static_cmap, static_space = static
    inst_upm, inst_glyphs, inst_cmap, inst_space = glyphs._load_instanced(family, weight)

    assert (static_upm, static_space) == (inst_upm, inst_space)
    assert static_cmap == inst_cmap
    for code, name in static_cmap.items():
        if 32 <= code < 127:
            assert static_glyphs[name].width == inst_glyphs[name].width, chr(code)


@pytest.mark.skipif(
    not _SCRIPT.is_file(), reason="scripts/instance_fonts.py is not part of this checkout"
)
def test_shipped_instances_are_not_stale():
    pytest.importorskip("fontTools.varLib.instancer")
    result = subprocess.run(
        [sys.executable, str(_SCRIPT), "--check"],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"shipped static font instances do not match a fresh build:\n{result.stdout}{result.stderr}"
    )


@pytest.mark.parametrize("variant", sorted(GOLDEN))
def test_rendered_card_matches_golden_digest(variant):
    actual = digests()[variant]
    assert actual == GOLDEN[variant], (
        f"the {variant} card changed: {GOLDEN[variant]} -> {actual}.\n"
        "Card rendering is deterministic, so this is a real output change. "
        "If it was intentional, eyeball the SVG and then refresh the digests "
        f"with: {UPDATE_COMMAND}"
    )
