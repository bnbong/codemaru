"""Vector icons + geometry for the summary card.

Ported from the codemaru design system (ui_kits/card/Icons.jsx). Everything is
pure SVG markup — no external assets — except the tier nameplate, which inlines a
downscaled calligraphy PNG as a base64 data URI so it renders even inside a
GitHub README image sandbox. Gradient ids carry a per-card token so multiple
cards on one page don't collide.

The tier emblem is a faceted hexagonal crest (game-rank style). Behind it, a
crest ornament evokes 마루 (summit / peak / sun): a sun-ray crown rises from
behind the hex — longest at the centre so it peaks like a summit — framed by
smooth laurel fronds, growing in ornateness from a bare Seed to a radiant Maru.
The five strength badges are medal-tinted tiles, each with a competency glyph.
"""

from __future__ import annotations

import math
from base64 import b64encode
from functools import lru_cache
from pathlib import Path

from codemaru.models.score import Axis, Tier
from codemaru.render.glyphs import MONO, text_path
from codemaru.render.themes import RANK_TINTS, TIER_COLORS, TIER_GRADIENTS, hex_to_rgba
from codemaru.render.xml import fmt_num

_ASSET_DIR = Path(__file__).parent / "assets" / "tiers"


def id_token(seed: str) -> str:
    """Stable, collision-resistant id suffix derived from a string (djb2 -> base36)."""
    h = 5381
    for ch in seed:
        h = ((h << 5) + h + ord(ch)) & 0xFFFFFFFF
    return _base36(h)


def _base36(n: int) -> str:
    if n == 0:
        return "0"
    digits = "0123456789abcdefghijklmnopqrstuvwxyz"
    out = []
    while n:
        n, rem = divmod(n, 36)
        out.append(digits[rem])
    return "".join(reversed(out))


# ---- emblem geometry --------------------------------------------------------


def _hex_verts(cx: float, cy: float, r: float) -> list[tuple[float, float]]:
    """Pointy-top hexagon vertices."""
    verts = []
    for i in range(6):
        a = math.radians(-90 + 60 * i)
        verts.append((cx + math.cos(a) * r, cy + math.sin(a) * r))
    return verts


def _pts(verts: list[tuple[float, float]]) -> str:
    return " ".join(f"{fmt_num(x)},{fmt_num(y)}" for x, y in verts)


# Per-edge bevel shading — top-left lit, bottom shadowed: (overlay color, alpha).
_FACET_SHADE: list[tuple[str, float]] = [
    ("#ffffff", 0.22),
    ("#ffffff", 0.07),
    ("#000000", 0.16),
    ("#000000", 0.24),
    ("#ffffff", 0.05),
    ("#ffffff", 0.30),
]


# ---- crest ornament (the 마루 motif) ----------------------------------------

_TIER_LEVEL: dict[Tier, int] = {
    Tier.SEED: 0,
    Tier.BRONZE: 1,
    Tier.SILVER: 2,
    Tier.GOLD: 3,
    Tier.PLATINUM: 4,
    Tier.DIAMOND: 5,
    Tier.MASTER: 6,
    Tier.MARU: 7,
}

# Per level: frond reach (deg up the side), bottom-swash scale, crown-spike count,
# spike fan span (deg), apex gem, side-sparkle count, swash/apex gem.
#
# The crown spikes read as a rank crown: Gold starts at 3 and each tier above
# adds exactly one (Platinum 4 → Maru 7). Below Gold there is no spike crown.
# The fan span widens with the count so the per-spike spacing stays even.
_ORNATE: list[dict[str, float | bool]] = [
    {"a1": 0, "swash": 0.0, "ray": 0, "span": 0, "apex": False, "spark": 0, "gem": False},
    {"a1": 150, "swash": 0.0, "ray": 0, "span": 0, "apex": False, "spark": 0, "gem": False},
    {"a1": 164, "swash": 0.70, "ray": 0, "span": 0, "apex": False, "spark": 0, "gem": False},
    {"a1": 176, "swash": 0.85, "ray": 3, "span": 38, "apex": True, "spark": 0, "gem": True},
    {"a1": 186, "swash": 0.95, "ray": 4, "span": 54, "apex": True, "spark": 0, "gem": True},
    {"a1": 194, "swash": 1.00, "ray": 5, "span": 68, "apex": True, "spark": 2, "gem": True},
    {"a1": 200, "swash": 1.05, "ray": 6, "span": 80, "apex": True, "spark": 2, "gem": True},
    {"a1": 206, "swash": 1.12, "ray": 7, "span": 90, "apex": True, "spark": 3, "gem": True},
]


def _pt_at(cx: float, cy: float, radius: float, deg: float, mirror: bool) -> tuple[float, float]:
    a = math.radians(deg)
    x = cx + math.cos(a) * radius
    y = cy + math.sin(a) * radius
    if mirror:
        x = 2 * cx - x
    return x, y


def _frond_path(cx: float, cy: float, r: float, a0: float, a1: float, mirror: bool) -> str:
    """A tapered metal frond hugging the emblem side — a smooth blade, not leaves."""
    steps = 26
    rc = r * 1.18
    tmax = r * 0.165
    out: list[tuple[float, float]] = []
    inn: list[tuple[float, float]] = []
    for k in range(steps + 1):
        t = k / steps
        deg = a0 + (a1 - a0) * t
        env = math.sin(math.pi * t) ** 0.85
        h = env * tmax
        out.append(_pt_at(cx, cy, rc + h, deg, mirror))
        inn.append(_pt_at(cx, cy, rc - h * 0.55, deg, mirror))
    pts = out + inn[::-1]
    return (
        " ".join(f"{'L' if i else 'M'}{fmt_num(x)} {fmt_num(y)}" for i, (x, y) in enumerate(pts))
        + " Z"
    )


def _curl_path(cx: float, cy: float, r: float, a1: float, mirror: bool) -> str:
    bx, by = _pt_at(cx, cy, r * 1.17, a1, mirror)
    d = -1 if mirror else 1
    s = r * 0.135
    return (
        f"M{fmt_num(bx)} {fmt_num(by)} "
        f"q{fmt_num(d * s * 1.1)} {fmt_num(-s * 0.2)} {fmt_num(d * s * 1.0)} {fmt_num(-s * 1.1)} "
        f"q{fmt_num(-d * s * 0.1)} {fmt_num(-s * 0.7)} {fmt_num(-d * s * 0.7)} {fmt_num(-s * 0.45)}"
    )


def _sparkle(cx: float, cy: float, s: float, fill: str) -> str:
    k = s * 0.16
    d = (
        f"M{fmt_num(cx)} {fmt_num(cy - s)} "
        f"C{fmt_num(cx + k)} {fmt_num(cy - k)} {fmt_num(cx + k)} {fmt_num(cy - k)} {fmt_num(cx + s)} {fmt_num(cy)} "
        f"C{fmt_num(cx + k)} {fmt_num(cy + k)} {fmt_num(cx + k)} {fmt_num(cy + k)} {fmt_num(cx)} {fmt_num(cy + s)} "
        f"C{fmt_num(cx - k)} {fmt_num(cy + k)} {fmt_num(cx - k)} {fmt_num(cy + k)} {fmt_num(cx - s)} {fmt_num(cy)} "
        f"C{fmt_num(cx - k)} {fmt_num(cy - k)} {fmt_num(cx - k)} {fmt_num(cy - k)} {fmt_num(cx)} {fmt_num(cy - s)} Z"
    )
    return f'<path d="{d}" fill="{fill}"/>'


def _summit_rays(cx: float, cy: float, r: float, n: int, span_deg: float, fill_id: str) -> str:
    """Sun / summit ray crown rising from behind the emblem (the 마루 motif)."""
    if not n:
        return ""
    center = -90.0
    rb = r * 0.96
    rays: list[str] = []
    for i in range(n):
        u = 0.0 if n == 1 else (i / (n - 1)) * 2 - 1
        deg = center + u * (span_deg / 2)
        len_f = 1 - 0.42 * u * u
        rt = rb + r * (0.30 + 0.44 * len_f)
        w = r * 0.05 * (0.6 + 0.4 * len_f)
        a = math.radians(deg)
        px, py = -math.sin(a) * w, math.cos(a) * w
        bx, by = cx + math.cos(a) * rb, cy + math.sin(a) * rb
        tx, ty = cx + math.cos(a) * rt, cy + math.sin(a) * rt
        rays.append(
            f'<path d="M{fmt_num(bx + px)} {fmt_num(by + py)} L{fmt_num(tx)} {fmt_num(ty)} '
            f'L{fmt_num(bx - px)} {fmt_num(by - py)} Z" fill="url(#{fill_id})"/>'
        )
    return "<g>" + "".join(rays) + "</g>"


def _gem_rhombus(cx: float, cy: float, s: float, hi: str, base: str, lo: str) -> str:
    return (
        '<g stroke-linejoin="round">'
        f'<polygon points="{fmt_num(cx)},{fmt_num(cy - s)} {fmt_num(cx + s * 0.66)},{fmt_num(cy)} '
        f'{fmt_num(cx)},{fmt_num(cy + s)} {fmt_num(cx - s * 0.66)},{fmt_num(cy)}" '
        f'fill="{base}" stroke="{lo}" stroke-width="0.6"/>'
        f'<polygon points="{fmt_num(cx)},{fmt_num(cy - s)} {fmt_num(cx + s * 0.66)},{fmt_num(cy)} '
        f'{fmt_num(cx)},{fmt_num(cy)} {fmt_num(cx - s * 0.66)},{fmt_num(cy)}" '
        f'fill="{hi}" fill-opacity="0.65"/>'
        f'<line x1="{fmt_num(cx)}" y1="{fmt_num(cy - s)}" x2="{fmt_num(cx)}" y2="{fmt_num(cy + s)}" '
        f'stroke="{lo}" stroke-width="0.4"/>'
        "</g>"
    )


def _crest_ornament(cx: float, cy: float, r: float, tier: Tier, token: str) -> str:
    lvl = _TIER_LEVEL[tier]
    if not lvl:
        return ""  # Seed: bare crest
    cfg = _ORNATE[lvl]
    hi, base, lo = TIER_GRADIENTS[tier]
    accent = TIER_COLORS[tier]
    a0 = 100.0
    a1 = float(cfg["a1"])

    defs = (
        "<defs>"
        f'<linearGradient id="frond-{token}" x1="0" y1="1" x2="0" y2="0">'
        f'<stop offset="0" stop-color="{lo}"/>'
        f'<stop offset="0.6" stop-color="{accent}"/>'
        f'<stop offset="1" stop-color="{hi}"/>'
        "</linearGradient>"
        f'<linearGradient id="ray-{token}" gradientUnits="userSpaceOnUse" '
        f'x1="{fmt_num(cx)}" y1="{fmt_num(cy)}" x2="{fmt_num(cx)}" y2="{fmt_num(cy - r * 1.8)}">'
        f'<stop offset="0" stop-color="{hex_to_rgba(accent, 0)}"/>'
        f'<stop offset="0.4" stop-color="{hex_to_rgba(accent, 0.55)}"/>'
        f'<stop offset="1" stop-color="{hi}"/>'
        "</linearGradient>"
        "</defs>"
    )

    rays = _summit_rays(cx, cy, r, int(cfg["ray"]), float(cfg["span"]), f"ray-{token}")

    fronds = []
    for mirror in (False, True):
        fronds.append(
            f'<path d="{_frond_path(cx, cy, r, a0, a1, mirror)}" fill="url(#frond-{token})" '
            f'stroke="{hex_to_rgba(lo, 0.5)}" stroke-width="0.5" stroke-linejoin="round"/>'
            f'<path d="{_curl_path(cx, cy, r, a1, mirror)}" fill="none" '
            f'stroke="{hex_to_rgba(hi, 0.9)}" stroke-width="{fmt_num(r * 0.045)}" stroke-linecap="round"/>'
        )

    swash = ""
    sw = float(cfg["swash"])
    if sw > 0:
        by = cy + r * 1.16
        span = r * 1.5 * sw

        def tail(m: bool) -> str:
            d = -1 if m else 1
            return (
                f"M{fmt_num(cx)} {fmt_num(by)} "
                f"C{fmt_num(cx + d * span * 0.4)} {fmt_num(by + r * 0.16)} "
                f"{fmt_num(cx + d * span * 0.78)} {fmt_num(by + r * 0.12)} "
                f"{fmt_num(cx + d * span)} {fmt_num(by - r * 0.12)}"
            )

        gem = (
            _gem_rhombus(cx, by - r * 0.02, r * 0.13, hi, accent, hex_to_rgba(lo, 0.8))
            if cfg["gem"]
            else ""
        )
        swash = (
            f'<g fill="none" stroke="url(#frond-{token})" stroke-width="{fmt_num(r * 0.05)}" '
            f'stroke-linecap="round"><path d="{tail(False)}"/><path d="{tail(True)}"/></g>{gem}'
        )

    sparks = ""
    if int(cfg["spark"]) >= 2:
        lx, ly = _pt_at(cx, cy, r * 1.34, a1 - 8, False)
        rx, ry = _pt_at(cx, cy, r * 1.34, a1 - 8, True)
        sparks = _sparkle(lx, ly, r * 0.15, hi) + _sparkle(rx, ry, r * 0.15, hi)

    apex = ""
    if cfg["apex"]:
        apex = _gem_rhombus(cx, cy - r * 1.74, r * 0.135, hi, accent, hex_to_rgba(lo, 0.85))

    return f"<g>{defs}{rays}{''.join(fronds)}{swash}{sparks}{apex}</g>"


def gradient_defs(tier: Tier, token: str) -> str:
    """Emblem metal gradient, recessed-medallion gradient, and panel glow."""
    hi, base, lo = TIER_GRADIENTS[tier]
    accent = TIER_COLORS[tier]
    return (
        "<defs>"
        f'<linearGradient id="emblem-{token}" x1="0.15" y1="0" x2="0.85" y2="1">'
        f'<stop offset="0" stop-color="{hi}"/>'
        f'<stop offset="0.5" stop-color="{base}"/>'
        f'<stop offset="1" stop-color="{lo}"/>'
        "</linearGradient>"
        f'<linearGradient id="plate-{token}" x1="0" y1="0" x2="0" y2="1">'
        f'<stop offset="0" stop-color="{hex_to_rgba(accent, 0.28)}"/>'
        '<stop offset="0.5" stop-color="rgba(13,17,23,0.92)"/>'
        '<stop offset="1" stop-color="rgba(13,17,23,0.98)"/>'
        "</linearGradient>"
        f'<radialGradient id="glow-{token}" cx="0.5" cy="0.5" r="0.5">'
        f'<stop offset="0" stop-color="{hex_to_rgba(accent, 0.34)}"/>'
        f'<stop offset="0.55" stop-color="{hex_to_rgba(accent, 0.10)}"/>'
        f'<stop offset="1" stop-color="{hex_to_rgba(accent, 0)}"/>'
        "</radialGradient>"
        "</defs>"
    )


def tier_emblem(cx: float, cy: float, r: float, tier: Tier, overall: float, token: str) -> str:
    """Faceted hexagonal crest with the crest ornament behind it."""
    accent = TIER_COLORS[tier]
    outer = _hex_verts(cx, cy, r)
    inner = _hex_verts(cx, cy, r * 0.6)
    plate = _hex_verts(cx, cy, r * 0.54)
    apex_y = cy - r

    facets = []
    for i in range(6):
        j = (i + 1) % 6
        quad = [outer[i], outer[j], inner[j], inner[i]]
        color, alpha = _FACET_SHADE[i]
        facets.append(
            f'<polygon points="{_pts(quad)}" fill="{color}" fill-opacity="{alpha}" '
            f'stroke="{color}" stroke-opacity="{fmt_num(alpha * 0.5)}" stroke-width="0.5" '
            'stroke-linejoin="round"/>'
        )

    return (
        "<g>"
        f"{_crest_ornament(cx, cy, r, tier, token)}"
        f'<polygon points="{_pts(_hex_verts(cx, cy, r + 1.5))}" fill="none" '
        'stroke="rgba(0,0,0,0.25)" stroke-width="2" stroke-linejoin="round"/>'
        f'<polygon points="{_pts(outer)}" fill="url(#emblem-{token})" stroke="{accent}" '
        'stroke-width="2" stroke-linejoin="round"/>'
        f"{''.join(facets)}"
        f'<polygon points="{_pts(_hex_verts(cx, cy, r * 0.94))}" fill="none" '
        'stroke="rgba(255,255,255,0.35)" stroke-width="0.8" stroke-linejoin="round"/>'
        f'<polygon points="{_pts(plate)}" fill="url(#plate-{token})" '
        f'stroke="{hex_to_rgba(accent, 0.55)}" stroke-width="1" stroke-linejoin="round"/>'
        f'<circle cx="{fmt_num(cx)}" cy="{fmt_num(apex_y + 0.5)}" r="{fmt_num(r * 0.085)}" '
        'fill="#fff" fill-opacity="0.9"/>'
        + text_path(
            str(round(overall)),
            family=MONO,
            weight=800,
            size=r * 0.62,
            x=cx,
            y=cy + r * 0.215,
            anchor="middle",
            fill="#f4f8fc",
            letter_spacing=-0.5,
        )
        + "</g>"
    )


# ---- strength competency glyphs ---------------------------------------------


def _glyph(axis: Axis, u: float, ink: str) -> str:
    """A competency glyph drawn around (0,0) on a ~16-unit field."""

    def p(x: float, y: float) -> str:
        return f"{fmt_num(x * u)} {fmt_num(y * u)}"

    def c(x: float) -> str:
        return fmt_num(x * u)

    sw = fmt_num(1.7 * u)
    common = f'fill="none" stroke="{ink}" stroke-width="{sw}" stroke-linecap="round" stroke-linejoin="round"'
    rr = fmt_num(1.7 * u)

    if axis is Axis.OPEN_SOURCE:  # git branch / fork
        return (
            "<g>"
            f'<circle cx="{c(-3.4)}" cy="{fmt_num(-5 * u)}" r="{rr}" {common}/>'
            f'<circle cx="{c(-3.4)}" cy="{fmt_num(5 * u)}" r="{rr}" {common}/>'
            f'<circle cx="{c(3.6)}" cy="{fmt_num(-5 * u)}" r="{rr}" {common}/>'
            f'<path d="M{p(-3.4, -3.3)} L{p(-3.4, 3.3)}" {common}/>'
            f'<path d="M{p(3.6, -3.3)} L{p(3.6, -1)} C{p(3.6, 1.6)} {p(-3.4, 0.4)} {p(-3.4, 3.1)}" {common}/>'
            "</g>"
        )
    if axis is Axis.PROBLEM_SOLVING:  # lightbulb
        return (
            "<g>"
            f'<path d="M{p(0, -6.4)} C{p(4.6, -6.4)} {p(5.2, -0.6)} {p(1.8, 1.6)} '
            f"L{p(1.8, 3.2)} L{p(-1.8, 3.2)} L{p(-1.8, 1.6)} "
            f'C{p(-5.2, -0.6)} {p(-4.6, -6.4)} {p(0, -6.4)} Z" {common}/>'
            f'<path d="M{p(-1.8, 4.6)} L{p(1.8, 4.6)}" {common}/>'
            f'<path d="M{p(-1.1, 6)} L{p(1.1, 6)}" {common}/>'
            "</g>"
        )
    if axis is Axis.IMPACT:  # star (filled)
        pts = []
        for i in range(10):
            rad = 6.4 if i % 2 == 0 else 2.6
            a = math.radians(-90 + i * 36)
            pts.append(f"{fmt_num(math.cos(a) * rad * u)},{fmt_num(math.sin(a) * rad * u)}")
        return (
            f'<polygon points="{" ".join(pts)}" fill="{ink}" stroke="{ink}" '
            f'stroke-width="{fmt_num(0.6 * u)}" stroke-linejoin="round"/>'
        )
    if axis is Axis.CONSISTENCY:  # flame (filled) + inner highlight
        return (
            "<g>"
            f'<path d="M{p(0, -6.6)} C{p(4.4, -1.6)} {p(3.8, 6)} {p(0, 6.4)} '
            f'C{p(-4, 6)} {p(-4.4, -0.4)} {p(0, -6.6)} Z" fill="{ink}" stroke="{ink}" '
            f'stroke-width="{fmt_num(0.6 * u)}" stroke-linejoin="round"/>'
            f'<path d="M{p(0, -0.6)} C{p(2.2, 1.4)} {p(1.8, 4.6)} {p(0, 4.8)} '
            f'C{p(-2, 4.6)} {p(-2.2, 2)} {p(0, -0.6)} Z" fill="rgba(255,255,255,0.55)"/>'
            "</g>"
        )
    if axis is Axis.DEPTH:  # layered stack
        return (
            "<g>"
            f'<path d="M{p(0, -6)} L{p(6.4, -2.6)} L{p(0, 0.8)} L{p(-6.4, -2.6)} Z" {common}/>'
            f'<path d="M{p(-6.4, 0.6)} L{p(0, 4)} L{p(6.4, 0.6)}" {common}/>'
            f'<path d="M{p(-6.4, 3.6)} L{p(0, 7)} L{p(6.4, 3.6)}" {common}/>'
            "</g>"
        )
    return ""


def strength_badge(cx: float, cy: float, s: float, axis: Axis, rank: int, token: str) -> str:
    """A medal-tinted tile + competency glyph. (cx, cy) is the tile center."""
    fill, border, ink = RANK_TINTS[min(rank, 2)]
    size = 30 * s
    half = size / 2
    u = s * 1.18
    gid = f"tile-{token}-{rank}"
    return (
        "<g>"
        "<defs>"
        f'<linearGradient id="{gid}" x1="0" y1="0" x2="0" y2="1">'
        f'<stop offset="0" stop-color="{fill}"/>'
        f'<stop offset="1" stop-color="{hex_to_rgba(border, 0.9)}"/>'
        "</linearGradient>"
        "</defs>"
        f'<rect x="{fmt_num(cx - half)}" y="{fmt_num(cy - half)}" width="{fmt_num(size)}" '
        f'height="{fmt_num(size)}" rx="{fmt_num(7 * s)}" fill="url(#{gid})" stroke="{border}" '
        f'stroke-width="{fmt_num(1.3 * s)}"/>'
        f'<rect x="{fmt_num(cx - half + 1.3 * s)}" y="{fmt_num(cy - half + 1.3 * s)}" '
        f'width="{fmt_num(size - 2.6 * s)}" height="{fmt_num(size * 0.42)}" rx="{fmt_num(5.5 * s)}" '
        'fill="rgba(255,255,255,0.30)"/>'
        f'<g transform="translate({fmt_num(cx)} {fmt_num(cy)})">{_glyph(axis, u, ink)}</g>'
        "</g>"
    )


# ---- tier nameplate (base64-inlined calligraphy) ----------------------------


@lru_cache(maxsize=len(Tier))
def _tier_name_data_uri(tier: Tier) -> str | None:
    path = _ASSET_DIR / f"{tier.value.lower()}.png"
    if not path.exists():
        return None
    encoded = b64encode(path.read_bytes()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def tier_nameplate(cx: float, yc: float, tier: Tier, box_w: float, box_h: float) -> str:
    """Tier name from the sliced calligraphy artwork, inlined as a data URI so it
    renders inside a GitHub README. Returns '' if the asset is missing."""
    uri = _tier_name_data_uri(tier)
    if uri is None:
        return ""
    x = cx - box_w / 2
    y = yc - box_h / 2
    return (
        f'<image href="{uri}" xlink:href="{uri}" x="{fmt_num(x)}" y="{fmt_num(y)}" '
        f'width="{fmt_num(box_w)}" height="{fmt_num(box_h)}" preserveAspectRatio="xMidYMid meet"/>'
    )
