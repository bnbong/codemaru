"""Vector icons: the tier emblem and the five strength trophies.

Everything is pure SVG path/shape markup — no external assets — so the card
stays self-contained for GitHub README embedding. Gradient fills reference
<defs> ids suffixed with a per-card token so multiple cards on one page don't
collide.
"""

from __future__ import annotations

import math
from collections.abc import Callable

from codemaru.models.score import Axis, Tier
from codemaru.render.themes import TIER_COLORS, TIER_GRADIENTS, hex_to_rgba
from codemaru.render.xml import fmt_num


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


def gradient_defs(tier: Tier, token: str) -> str:
    """<defs> block: the emblem fill gradient and the tier-tinted panel wash."""
    grad_from, grad_to = TIER_GRADIENTS[tier]
    accent = TIER_COLORS[tier]
    return (
        "<defs>"
        f'<linearGradient id="emblem-{token}" x1="0" y1="0" x2="0" y2="1">'
        f'<stop offset="0" stop-color="{grad_from}"/>'
        f'<stop offset="1" stop-color="{grad_to}"/>'
        "</linearGradient>"
        f'<linearGradient id="panel-{token}" x1="0" y1="0" x2="0" y2="1">'
        f'<stop offset="0" stop-color="{hex_to_rgba(accent, 0.35)}"/>'
        f'<stop offset="0.55" stop-color="{hex_to_rgba(accent, 0.08)}"/>'
        f'<stop offset="1" stop-color="{hex_to_rgba(accent, 0)}"/>'
        "</linearGradient>"
        "</defs>"
    )


def _hex_points(cx: float, cy: float, r: float) -> str:
    """Pointy-top hexagon point string."""
    parts = []
    for i in range(6):
        a = math.radians(-90 + 60 * i)
        parts.append(f"{fmt_num(cx + math.cos(a) * r)},{fmt_num(cy + math.sin(a) * r)}")
    return " ".join(parts)


def tier_emblem(cx: float, cy: float, r: float, tier: Tier, overall: float, token: str) -> str:
    """Game-style hexagonal rank badge: gradient fill, inner bevel, score, sparkle."""
    accent = TIER_COLORS[tier]
    outer = _hex_points(cx, cy, r)
    inner = _hex_points(cx, cy, r * 0.74)
    sy = cy - r - 1
    return (
        "<g>"
        f'<polygon points="{outer}" fill="url(#emblem-{token})" stroke="{accent}" '
        'stroke-width="2.5" stroke-linejoin="round"/>'
        f'<polygon points="{inner}" fill="none" stroke="rgba(255,255,255,0.45)" stroke-width="1"/>'
        f'<path d="M{fmt_num(cx)} {fmt_num(sy - 4)} L{fmt_num(cx + 1.6)} {fmt_num(sy)} '
        f'L{fmt_num(cx)} {fmt_num(sy + 4)} L{fmt_num(cx - 1.6)} {fmt_num(sy)} Z" fill="{accent}"/>'
        f'<text x="{fmt_num(cx)}" y="{fmt_num(cy + r * 0.32)}" text-anchor="middle" '
        f'fill="#10141a" font-size="{fmt_num(r * 0.78)}" font-weight="800" '
        f'font-family="Segoe UI, Helvetica, Arial, sans-serif">{round(overall)}</text>'
        "</g>"
    )


TrophyFn = Callable[[float, float, float, str, str], str]


def _p(cx: float, cy: float, s: float, x: float, y: float) -> str:
    """A scaled, translated point as 'X Y' (for path data)."""
    return f"{fmt_num(cx + x * s)} {fmt_num(cy + y * s)}"


def _pc(cx: float, cy: float, s: float, x: float, y: float) -> str:
    """A scaled, translated point as 'X,Y' (for polygon points)."""
    return f"{fmt_num(cx + x * s)},{fmt_num(cy + y * s)}"


def _cup(cx: float, cy: float, s: float, fill: str, stroke: str) -> str:
    return (
        f'<g stroke="{stroke}" stroke-width="{fmt_num(1.2 * s)}" stroke-linejoin="round">'
        f'<path d="M{_p(cx, cy, s, -7, -10)} L{_p(cx, cy, s, 7, -10)} L{_p(cx, cy, s, 6, -3)} '
        f'Q{_p(cx, cy, s, 0, 5)} {_p(cx, cy, s, -6, -3)} Z" fill="{fill}"/>'
        f'<path d="M{_p(cx, cy, s, -7, -9)} Q{_p(cx, cy, s, -12, -8)} {_p(cx, cy, s, -9, -3)} '
        f'Q{_p(cx, cy, s, -7, -2)} {_p(cx, cy, s, -6, -4)}" fill="none"/>'
        f'<path d="M{_p(cx, cy, s, 7, -9)} Q{_p(cx, cy, s, 12, -8)} {_p(cx, cy, s, 9, -3)} '
        f'Q{_p(cx, cy, s, 7, -2)} {_p(cx, cy, s, 6, -4)}" fill="none"/>'
        f'<rect x="{fmt_num(cx - 1.6 * s)}" y="{fmt_num(cy + 3 * s)}" width="{fmt_num(3.2 * s)}" '
        f'height="{fmt_num(4 * s)}" fill="{fill}"/>'
        f'<rect x="{fmt_num(cx - 6 * s)}" y="{fmt_num(cy + 7 * s)}" width="{fmt_num(12 * s)}" '
        f'height="{fmt_num(3 * s)}" rx="{fmt_num(1 * s)}" fill="{fill}"/>'
        "</g>"
    )


def _star_medal(cx: float, cy: float, s: float, fill: str, stroke: str) -> str:
    pts = []
    for i in range(10):
        rad = 6.2 * s if i % 2 == 0 else 2.7 * s
        a = math.radians(-90 + i * 36)
        pts.append(f"{fmt_num(cx + math.cos(a) * rad)},{fmt_num(cy + math.sin(a) * rad)}")
    star = " ".join(pts)
    return (
        f'<g stroke="{stroke}" stroke-width="{fmt_num(1.2 * s)}" stroke-linejoin="round">'
        f'<circle cx="{fmt_num(cx)}" cy="{fmt_num(cy)}" r="{fmt_num(9.5 * s)}" fill="{fill}"/>'
        f'<polygon points="{star}" fill="{stroke}" stroke="none"/>'
        "</g>"
    )


def _flame(cx: float, cy: float, s: float, fill: str, stroke: str) -> str:
    return (
        f'<g stroke="{stroke}" stroke-width="{fmt_num(1.2 * s)}" stroke-linejoin="round">'
        f'<path d="M{_p(cx, cy, s, 0, -11)} C{_p(cx, cy, s, 8, -3)} {_p(cx, cy, s, 6, 9)} '
        f"{_p(cx, cy, s, 0, 10)} C{_p(cx, cy, s, -7, 9)} {_p(cx, cy, s, -8, -1)} "
        f'{_p(cx, cy, s, 0, -11)} Z" fill="{fill}"/>'
        f'<path d="M{_p(cx, cy, s, 0, -3)} C{_p(cx, cy, s, 4, 1)} {_p(cx, cy, s, 3, 7)} '
        f"{_p(cx, cy, s, 0, 8)} C{_p(cx, cy, s, -3, 7)} {_p(cx, cy, s, -4, 2)} "
        f'{_p(cx, cy, s, 0, -3)} Z" fill="{stroke}" stroke="none"/>'
        "</g>"
    )


def _ribbon_medal(cx: float, cy: float, s: float, fill: str, stroke: str) -> str:
    return (
        f'<g stroke="{stroke}" stroke-width="{fmt_num(1.2 * s)}" stroke-linejoin="round">'
        f'<path d="M{_p(cx, cy, s, -5, -11)} L{_p(cx, cy, s, -1, -1)} L{_p(cx, cy, s, -7, -1)} Z" '
        f'fill="{fill}"/>'
        f'<path d="M{_p(cx, cy, s, 5, -11)} L{_p(cx, cy, s, 1, -1)} L{_p(cx, cy, s, 7, -1)} Z" '
        f'fill="{fill}"/>'
        f'<circle cx="{fmt_num(cx)}" cy="{fmt_num(cy + 4 * s)}" '
        f'r="{fmt_num(7 * s)}" fill="{fill}"/>'
        f'<circle cx="{fmt_num(cx)}" cy="{fmt_num(cy + 4 * s)}" r="{fmt_num(3.2 * s)}" '
        f'fill="{stroke}" stroke="none"/>'
        "</g>"
    )


def _gem(cx: float, cy: float, s: float, fill: str, stroke: str) -> str:
    lower = f"{_pc(cx, cy, s, -9, -5)} {_pc(cx, cy, s, 9, -5)} {_pc(cx, cy, s, 0, 11)}"
    upper = (
        f"{_pc(cx, cy, s, -9, -5)} {_pc(cx, cy, s, -4, -10)} "
        f"{_pc(cx, cy, s, 4, -10)} {_pc(cx, cy, s, 9, -5)}"
    )
    facets = (
        f"M{_p(cx, cy, s, -4, -10)} L{_p(cx, cy, s, -2, -5)} "
        f"M{_p(cx, cy, s, 4, -10)} L{_p(cx, cy, s, 2, -5)} "
        f"M{_p(cx, cy, s, -9, -5)} L{_p(cx, cy, s, 0, 11)} "
        f"M{_p(cx, cy, s, 9, -5)} L{_p(cx, cy, s, 0, 11)} "
        f"M{_p(cx, cy, s, -2, -5)} L{_p(cx, cy, s, 2, -5)}"
    )
    return (
        f'<g stroke="{stroke}" stroke-width="{fmt_num(1.2 * s)}" stroke-linejoin="round">'
        f'<polygon points="{lower}" fill="{fill}"/>'
        f'<polygon points="{upper}" fill="{fill}"/>'
        f'<path d="{facets}" fill="none" stroke="rgba(255,255,255,0.5)" '
        f'stroke-width="{fmt_num(0.8 * s)}"/>'
        "</g>"
    )


TROPHY_ICONS: dict[Axis, TrophyFn] = {
    Axis.OPEN_SOURCE: _cup,
    Axis.IMPACT: _star_medal,
    Axis.CONSISTENCY: _flame,
    Axis.PROBLEM_SOLVING: _ribbon_medal,
    Axis.DEPTH: _gem,
}
