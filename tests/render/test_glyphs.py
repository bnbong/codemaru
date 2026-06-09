"""Tests for the text-outlining helpers in codemaru.render.glyphs."""

from __future__ import annotations

from codemaru.render.glyphs import MONO, SANS, defs_markup, glyph_defs, text_path, text_width


def test_defs_markup_empty_registry_is_blank():
    assert defs_markup({}) == ""


def test_text_path_empty_string_is_blank():
    assert text_path("", family=SANS, weight=500, size=10, x=0, y=0, fill="#000") == ""


def test_text_path_inline_fallback_without_render_context():
    # No glyph_defs() active -> glyphs are inlined as <path>, not <use> refs.
    out = text_path("A", family=MONO, weight=500, size=12, x=0, y=0, fill="#000")
    assert "<path" in out
    assert "<use" not in out


def test_text_path_inside_context_uses_refs_and_collects_defs():
    with glyph_defs() as registry:
        out = text_path("A", family=MONO, weight=500, size=12, x=0, y=0, fill="#000")
    assert "<use" in out
    assert "<path" not in out  # the path lives in the shared defs, not inline
    assert defs_markup(registry).startswith("<defs>")


def test_text_path_opacity_emits_fill_opacity():
    out = text_path("A", family=SANS, weight=400, size=10, x=0, y=0, fill="#000", opacity=0.5)
    assert "fill-opacity" in out


def test_unmapped_char_draws_nothing_but_still_advances():
    # A glyph absent from the font (Hangul isn't in JetBrains Mono) draws no
    # outline but still advances like a space, so layout never collapses.
    out = text_path("한", family=MONO, weight=500, size=12, x=0, y=10, fill="#000")
    assert "<use" not in out and "<path" not in out  # no glyph emitted
    assert text_width("한", family=MONO, weight=500, size=12) > 0  # space-width advance
