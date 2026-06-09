"""Render text as vector outlines (SVG ``<path>``) instead of ``<text>``.

GitHub renders a README's card SVG through an ``<img>`` in *secure static mode*:
external/web fonts and ``@font-face`` are ignored, so ``<text>`` falls back to
whatever font the viewer's OS happens to have (Helvetica/SF Mono on macOS,
Segoe UI/Consolas on Windows) — the card looks inconsistent and "cheap".

Outlining the text to paths bakes the *designed* fonts (Space Grotesk,
JetBrains Mono — both OFL, freely embeddable) into the SVG geometry, so the card
renders identically on every OS and browser. Glyph outlines and per-weight font
instances are cached; the variable fonts are instanced to the exact weight used.
"""

from __future__ import annotations

import contextvars
from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path
from typing import Any

from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.ttLib import TTFont
from fontTools.varLib import instancer

from codemaru.render.xml import escape_xml, fmt_num

# During one card render, repeated glyphs (digits, common letters) are defined
# once in a shared <defs> and referenced with <use>, which shrinks the SVG by
# ~80%. The sink is a render-scoped {glyph-id: path} map; when no render context
# is active (e.g. a standalone text_path call), glyphs fall back to inline paths.
_sink: contextvars.ContextVar[dict[str, str] | None] = contextvars.ContextVar(
    "glyph_sink", default=None
)


@contextmanager
def glyph_defs() -> Iterator[dict[str, str]]:
    """Collect deduplicated glyph paths for one render; yields the id->path map."""
    registry: dict[str, str] = {}
    token = _sink.set(registry)
    try:
        yield registry
    finally:
        _sink.reset(token)


def defs_markup(registry: dict[str, str]) -> str:
    """Render the collected glyph paths as a single <defs> block."""
    if not registry:
        return ""
    paths = "".join(f'<path id="{gid}" d="{d}"/>' for gid, d in registry.items())
    return f"<defs>{paths}</defs>"


_FONT_DIR = Path(__file__).parent / "assets" / "fonts"

# Logical family name -> variable font file.
SANS = "sans"
MONO = "mono"
_FILES = {SANS: "SpaceGrotesk.ttf", MONO: "JetBrainsMono.ttf"}


@lru_cache(maxsize=16)
def _instance(family: str, weight: int) -> tuple[int, Any, dict[int, str], float]:
    """Instance a variable font to ``weight``; return (upm, glyphset, cmap, space)."""
    font = TTFont(_FONT_DIR / _FILES[family])
    # Clamp the requested weight to the font's axis range before instancing.
    axis = next(a for a in font["fvar"].axes if a.axisTag == "wght")
    w = max(axis.minValue, min(axis.maxValue, float(weight)))
    inst = instancer.instantiateVariableFont(font, {"wght": w}, inplace=False)
    upm = int(inst["head"].unitsPerEm)
    glyphset = inst.getGlyphSet()
    cmap = inst.getBestCmap()
    space = glyphset[cmap[ord(" ")]].width if ord(" ") in cmap else upm * 0.5
    return upm, glyphset, cmap, float(space)


@lru_cache(maxsize=8192)
def _glyph(family: str, weight: int, ch: str) -> tuple[str, float]:
    """Return (SVG path commands in font units, advance width) for one char."""
    _upm, glyphset, cmap, space = _instance(family, weight)
    name = cmap.get(ord(ch))
    if name is None:  # unmapped char: advance like a space, draw nothing
        return "", space
    glyph = glyphset[name]
    pen = SVGPathPen(glyphset)
    glyph.draw(pen)
    return pen.getCommands(), float(glyph.width)


def text_width(
    text: str, *, family: str, weight: int, size: float, letter_spacing: float = 0.0
) -> float:
    """Advance-based pixel width of ``text`` at the given size (for anchoring)."""
    upm, *_ = _instance(family, weight)
    scale = size / upm
    advance = sum(_glyph(family, weight, ch)[1] for ch in text) * scale
    if len(text) > 1:
        advance += letter_spacing * (len(text) - 1)
    return advance


def text_path(
    text: str,
    *,
    family: str,
    weight: int,
    size: float,
    x: float,
    y: float,
    anchor: str = "start",
    fill: str,
    letter_spacing: float = 0.0,
    opacity: float | None = None,
) -> str:
    """Outline ``text`` to SVG paths, positioned like a ``<text>`` element.

    ``(x, y)`` is the anchor point on the text baseline; ``anchor`` is
    ``start`` | ``middle`` | ``end`` — matching the SVG ``text-anchor`` it
    replaces, so callers can drop this in using the same coordinates.
    """
    if not text:
        return ""
    upm, *_ = _instance(family, weight)
    scale = size / upm
    width = text_width(text, family=family, weight=weight, size=size, letter_spacing=letter_spacing)
    if anchor == "middle":
        ox = x - width / 2
    elif anchor == "end":
        ox = x - width
    else:
        ox = x

    ls_units = letter_spacing / scale  # px gap -> font units (undone by the scale)
    pen_units = 0.0
    sink = _sink.get()
    glyphs: list[str] = []
    for ch in text:
        cmds, adv = _glyph(family, weight, ch)
        if cmds:
            if sink is None:
                glyphs.append(f'<path transform="translate({fmt_num(pen_units)} 0)" d="{cmds}"/>')
            else:
                gid = f"g{family[0]}{weight}_{ord(ch)}"
                if gid not in sink:
                    sink[gid] = cmds
                glyphs.append(f'<use href="#{gid}" xlink:href="#{gid}" x="{fmt_num(pen_units)}"/>')
        pen_units += adv + ls_units

    attrs = f'fill="{fill}"'
    if opacity is not None:
        attrs += f' fill-opacity="{fmt_num(opacity)}"'
    # Outlined glyphs carry no text, so expose the string to assistive tech (and
    # tests) via an escaped aria-label on the group.
    label = f'role="text" aria-label="{escape_xml(text)}"'
    # One outer transform places the baseline at (ox, y) and flips font y-up to
    # SVG y-down; glyphs inside are offset by their advance in font units.
    # The scale factor (size/1000, e.g. 0.0125) needs more precision than
    # fmt_num's 2 decimals — rounding it to 0.01 would shrink the text ~20%.
    return (
        f'<g {label} transform="translate({fmt_num(ox)} {fmt_num(y)}) '
        f'scale({scale:.6g} {-scale:.6g})" {attrs}>{"".join(glyphs)}</g>'
    )
