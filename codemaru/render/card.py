"""Card renderer. Produces a deterministic, self-contained SVG string for a
CodemaruSummary.

Layout:
  - default: tier panel (emblem + strength trophies + handle), a right 5-axis
    radar chart, and a supporting-metric row beneath the radar.
  - compact: the tier panel only (no radar, no metric row, no footer).

All colors come from theme tokens; all user-derived text is escaped and length-
capped; coordinates are fixed per layout so text never overflows.
"""

from __future__ import annotations

from dataclasses import dataclass

from codemaru.models.render import RenderOptions
from codemaru.models.score import AXES, AXIS_LABELS, AXIS_SHORT_LABELS
from codemaru.models.summary import CodemaruSummary
from codemaru.render.icons import TROPHY_ICONS, gradient_defs, id_token, tier_emblem
from codemaru.render.radar import polygon_points, ring_fractions, vertex
from codemaru.render.themes import RANK_TINTS, TIER_COLORS, Theme, get_theme
from codemaru.render.xml import fmt_num, safe_text

_FONT = "Segoe UI, Helvetica, Arial, sans-serif"


@dataclass(frozen=True)
class _Layout:
    width: int
    height: int
    panel_width: int
    emblem_cx: float
    emblem_cy: float
    emblem_r: float
    tier_name_y: float
    caption_y: float
    trophy_cy: float
    trophy_label_y: float
    trophy_spacing: float
    trophy_scale: float
    handle_y: float
    footer_y: float
    radar: tuple[float, float, float] | None  # (cx, cy, radius)
    metrics_y: float | None


_DEFAULT = _Layout(
    width=640,
    height=300,
    panel_width=210,
    emblem_cx=105,
    emblem_cy=84,
    emblem_r=34,
    tier_name_y=140,
    caption_y=162,
    trophy_cy=188,
    trophy_label_y=206,
    trophy_spacing=58,
    trophy_scale=0.92,
    handle_y=282,
    footer_y=293,
    radar=(425, 118, 84),
    metrics_y=258,
)

_COMPACT = _Layout(
    width=250,
    height=256,
    panel_width=250,
    emblem_cx=125,
    emblem_cy=86,
    emblem_r=36,
    tier_name_y=146,
    caption_y=168,
    trophy_cy=194,
    trophy_label_y=212,
    trophy_spacing=66,
    trophy_scale=0.96,
    handle_y=242,
    footer_y=244,  # unused in compact (no footer)
    radar=None,
    metrics_y=None,
)


def _background(layout: _Layout, theme: Theme, token: str) -> str:
    fill = "none" if theme.bg == "transparent" else theme.bg
    card = (
        f'<rect x="0.5" y="0.5" width="{layout.width - 1}" height="{layout.height - 1}" '
        f'rx="10" fill="{fill}" stroke="{theme.border}"/>'
    )
    if layout.radar is not None:
        panel = (
            f'<rect x="1" y="1" width="{layout.panel_width}" height="{layout.height - 2}" '
            f'rx="10" fill="{theme.panel_bg}"/>'
            f'<rect x="1" y="1" width="{layout.panel_width}" height="{layout.height - 2}" '
            f'rx="10" fill="url(#panel-{token})"/>'
        )
        divider = (
            f'<line x1="{layout.panel_width + 1}" y1="14" x2="{layout.panel_width + 1}" '
            f'y2="{layout.height - 14}" stroke="{theme.border}" stroke-width="1"/>'
        )
        return card + panel + divider
    wash = (
        f'<rect x="0.5" y="0.5" width="{layout.width - 1}" height="{layout.height - 1}" '
        f'rx="10" fill="url(#panel-{token})"/>'
    )
    return card + wash


def _tier_panel(summary: CodemaruSummary, layout: _Layout, theme: Theme, token: str) -> str:
    scores = summary.scores
    tier_color = TIER_COLORS[scores.tier]
    cx = layout.panel_width / 2
    handle = safe_text(summary.input.github, 24 if layout.panel_width > 220 else 18)

    wordmark = (
        f'<text x="{fmt_num(cx)}" y="26" text-anchor="middle" fill="{theme.muted}" '
        f'font-size="12" letter-spacing="1.5" font-family="{_FONT}">codemaru</text>'
    )
    emblem = tier_emblem(
        layout.emblem_cx, layout.emblem_cy, layout.emblem_r, scores.tier, scores.overall, token
    )
    tier_name = (
        f'<text x="{fmt_num(cx)}" y="{fmt_num(layout.tier_name_y)}" text-anchor="middle" '
        f'fill="{tier_color}" font-size="22" font-weight="800" font-family="{_FONT}">'
        f"{safe_text(scores.tier.value, 12)}</text>"
    )
    caption = (
        f'<text x="{fmt_num(cx)}" y="{fmt_num(layout.caption_y)}" text-anchor="middle" '
        f'fill="{theme.muted}" font-size="9" letter-spacing="1.5" font-family="{_FONT}">'
        "TOP STRENGTHS</text>"
    )
    trophies = _strength_trophies(summary, layout, theme)
    handle_text = (
        f'<text x="{fmt_num(cx)}" y="{fmt_num(layout.handle_y)}" text-anchor="middle" '
        f'fill="{theme.text}" font-size="13" font-weight="600" font-family="{_FONT}">'
        f"@{handle}</text>"
    )
    return f"<g>{wordmark}{emblem}{tier_name}{caption}{trophies}{handle_text}</g>"


def _strength_trophies(summary: CodemaruSummary, layout: _Layout, theme: Theme) -> str:
    cx = layout.panel_width / 2
    strengths = summary.strengths[:3]
    count = len(strengths)
    offsets = [-1.0, 0.0, 1.0] if count == 3 else [i - (count - 1) / 2 for i in range(count)]
    out: list[str] = []
    for i, axis in enumerate(strengths):
        tint_fill, tint_stroke = RANK_TINTS[i] if i < len(RANK_TINTS) else RANK_TINTS[-1]
        x = cx + offsets[i] * layout.trophy_spacing
        out.append(
            TROPHY_ICONS[axis](x, layout.trophy_cy, layout.trophy_scale, tint_fill, tint_stroke)
        )
        out.append(
            f'<text x="{fmt_num(x)}" y="{fmt_num(layout.trophy_label_y)}" text-anchor="middle" '
            f'fill="{theme.muted}" font-size="9" font-family="{_FONT}">'
            f"{safe_text(AXIS_SHORT_LABELS[axis], 10)}</text>"
        )
    return "".join(out)


def _radar(summary: CodemaruSummary, layout: _Layout, theme: Theme) -> str:
    if layout.radar is None:
        return ""
    cx, cy, radius = layout.radar
    count = len(AXES)

    rings = "".join(
        f'<polygon points="{polygon_points(cx, cy, radius, [f] * count)}" fill="none" '
        f'stroke="{theme.grid}" stroke-width="1"/>'
        for f in ring_fractions(4)
    )

    spokes: list[str] = []
    for i, axis in enumerate(AXES):
        tx, ty = vertex(cx, cy, radius, i, count, 1)
        lx, ly = vertex(cx, cy, radius, i, count, 1.24)
        dx = lx - cx
        anchor = "middle" if abs(dx) < 6 else ("start" if dx > 0 else "end")
        spokes.append(
            f'<line x1="{fmt_num(cx)}" y1="{fmt_num(cy)}" x2="{fmt_num(tx)}" y2="{fmt_num(ty)}" '
            f'stroke="{theme.grid}" stroke-width="1"/>'
            f'<text x="{fmt_num(lx)}" y="{fmt_num(ly)}" text-anchor="{anchor}" '
            f'fill="{theme.muted}" font-size="10" font-family="{_FONT}">'
            f"{safe_text(AXIS_LABELS[axis], 16)}</text>"
        )

    fractions = [summary.scores.axes.get(a) / 100 for a in AXES]
    data = polygon_points(cx, cy, radius, fractions)
    series = (
        f'<polygon points="{data}" fill="{theme.radar_fill}" stroke="{theme.radar_stroke}" '
        'stroke-width="2" stroke-linejoin="round"/>'
    )
    return f"<g>{rings}{''.join(spokes)}{series}</g>"


def _metrics_row(summary: CodemaruSummary, layout: _Layout, theme: Theme) -> str:
    if layout.metrics_y is None:
        return ""
    metrics = summary.metrics[:6]
    if not metrics:
        return ""
    start_x = layout.panel_width + 16
    end_x = layout.width - 16
    step = (end_x - start_x) / len(metrics)
    y = layout.metrics_y

    cells: list[str] = []
    for i, m in enumerate(metrics):
        x = start_x + step * i + step / 2
        value = safe_text(m.value, 12)
        label = safe_text(m.label, 12)
        cells.append(
            f'<text x="{fmt_num(x)}" y="{fmt_num(y)}" text-anchor="middle" fill="{theme.text}" '
            f'font-size="13" font-weight="600" font-family="{_FONT}">{value}</text>'
            f'<text x="{fmt_num(x)}" y="{fmt_num(y + 16)}" text-anchor="middle" '
            f'fill="{theme.muted}" font-size="10" font-family="{_FONT}">{label}</text>'
        )
    divider = (
        f'<line x1="{start_x}" y1="{fmt_num(y - 26)}" x2="{end_x}" y2="{fmt_num(y - 26)}" '
        f'stroke="{theme.border}" stroke-width="1"/>'
    )
    return f"<g>{divider}{''.join(cells)}</g>"


def _footer(summary: CodemaruSummary, layout: _Layout, theme: Theme) -> str:
    date = summary.updated_at.date().isoformat()
    stale = summary.overall_status.value != "ok"
    x = layout.panel_width + 16
    left = f"scoreVersion {safe_text(summary.scores.score_version, 10)} · {date}"
    badge = (
        f'<text x="{layout.width - 14}" y="{fmt_num(layout.footer_y)}" text-anchor="end" '
        f'fill="{theme.muted}" font-size="9" font-family="{_FONT}">partial data</text>'
        if stale
        else ""
    )
    return (
        f'<text x="{x}" y="{fmt_num(layout.footer_y)}" fill="{theme.muted}" font-size="9" '
        f'font-family="{_FONT}">{left}</text>{badge}'
    )


def render_card(summary: CodemaruSummary, options: RenderOptions | None = None) -> str:
    """Render a full card SVG for the summary."""
    opts = options or RenderOptions()
    layout = _COMPACT if opts.compact else _DEFAULT
    theme = get_theme(opts.theme)
    token = id_token(f"{summary.input.github}:{summary.scores.tier.value}")

    parts = [
        gradient_defs(summary.scores.tier, token),
        _background(layout, theme, token),
        _tier_panel(summary, layout, theme, token),
        _radar(summary, layout, theme),
        _metrics_row(summary, layout, theme),
        # Compact shows only tier, trophies, and handle — no footer.
        "" if opts.compact else _footer(summary, layout, theme),
    ]
    return _svg_document(layout, summary, "".join(parts))


def render_error_card(message: str, options: RenderOptions | None = None) -> str:
    """A minimal error card so failures never return a blank/broken image."""
    opts = options or RenderOptions()
    layout = _COMPACT if opts.compact else _DEFAULT
    theme = get_theme(opts.theme)
    fill = "none" if theme.bg == "transparent" else theme.bg
    body = (
        f'<rect x="0.5" y="0.5" width="{layout.width - 1}" height="{layout.height - 1}" '
        f'rx="10" fill="{fill}" stroke="{theme.border}"/>'
        f'<text x="{layout.width / 2}" y="{layout.height / 2 - 8}" text-anchor="middle" '
        f'fill="{theme.title}" font-size="16" font-weight="700" '
        f'font-family="{_FONT}">codemaru</text>'
        f'<text x="{layout.width / 2}" y="{layout.height / 2 + 16}" text-anchor="middle" '
        f'fill="{theme.muted}" font-size="12" font-family="{_FONT}">{safe_text(message, 60)}</text>'
    )
    return _svg_document(layout, None, body)


def _svg_document(layout: _Layout, summary: CodemaruSummary | None, body: str) -> str:
    if summary is not None:
        title = (
            f"codemaru card for {safe_text(summary.input.github, 39)} — {summary.scores.tier.value}"
        )
    else:
        title = "codemaru card"
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{layout.width}" height="{layout.height}" '
        f'viewBox="0 0 {layout.width} {layout.height}" role="img" aria-label="{title}">'
        f"<title>{title}</title>{body}</svg>"
    )
