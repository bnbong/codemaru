"""Card renderer. Produces a deterministic, self-contained SVG string for a
CodemaruSummary.

Layout (ported from the codemaru design system, ui_kits/card/Card.jsx):
  - default 640x300: tier panel (faceted emblem + 마루 crest ornament + calligraphy
    tier name + 3 strength badges + GitHub-linked handle + bottom wordmark), a
    right 5-axis radar chart, and a supporting-metric row.
  - compact 250x270: the tier panel only (no radar, metric row, or footer).

All colors come from theme tokens; user-derived text is escaped and length-
capped; coordinates are fixed per layout so text never overflows.
"""

from __future__ import annotations

from dataclasses import dataclass

from codemaru.models.render import RenderOptions
from codemaru.models.score import AXES, AXIS_LABELS, AXIS_SHORT_LABELS
from codemaru.models.summary import CodemaruSummary
from codemaru.render.glyphs import MONO, SANS, defs_markup, glyph_defs, text_path, text_width
from codemaru.render.icons import (
    gradient_defs,
    id_token,
    strength_badge,
    tier_emblem,
    tier_nameplate,
)
from codemaru.render.radar import polygon_points, ring_fractions, vertex
from codemaru.render.themes import Theme, get_theme
from codemaru.render.xml import escape_xml, fmt_num, safe_text, truncate


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
    wordmark_y: float
    footer_y: float
    glow_r: float
    radar: tuple[float, float, float] | None  # (cx, cy, radius)
    metrics_y: float | None


_DEFAULT = _Layout(
    width=640,
    height=300,
    panel_width=210,
    emblem_cx=105,
    emblem_cy=74,
    emblem_r=32,
    tier_name_y=146,
    caption_y=190,
    trophy_cy=211,
    trophy_label_y=237,
    trophy_spacing=58,
    trophy_scale=0.9,
    handle_y=274,
    wordmark_y=291,
    footer_y=294,
    glow_r=150,
    radar=(425, 118, 84),
    metrics_y=258,
)

_COMPACT = _Layout(
    width=250,
    height=270,
    panel_width=250,
    emblem_cx=125,
    emblem_cy=72,
    emblem_r=35,
    tier_name_y=142,
    caption_y=180,
    trophy_cy=201,
    trophy_label_y=228,
    trophy_spacing=66,
    trophy_scale=0.94,
    # Handle and wordmark need the same vertical breathing room as the default
    # layout (≈19px between them, ≈7px to the bottom edge); otherwise the
    # underlined @handle and the "codemaru" wordmark collide.
    handle_y=244,
    wordmark_y=263,
    footer_y=266,  # unused in compact (no footer)
    glow_r=170,
    radar=None,
    metrics_y=None,
)


def _background(layout: _Layout, theme: Theme, token: str) -> str:
    fill = "none" if theme.bg == "transparent" else theme.bg
    clip_w = layout.panel_width if layout.radar is not None else layout.width - 2
    clip = (
        f'<clipPath id="panelclip-{token}">'
        f'<rect x="1" y="1" width="{clip_w}" height="{layout.height - 2}" rx="10"/>'
        "</clipPath>"
    )
    card = (
        f'<rect x="0.5" y="0.5" width="{layout.width - 1}" height="{layout.height - 1}" '
        f'rx="10" fill="{fill}" stroke="{theme.border}"/>'
    )
    glow = (
        f'<g clip-path="url(#panelclip-{token})">'
        f'<circle cx="{fmt_num(layout.emblem_cx)}" cy="{fmt_num(layout.emblem_cy)}" '
        f'r="{fmt_num(layout.glow_r)}" fill="url(#glow-{token})"/></g>'
    )
    if layout.radar is not None:
        panel = (
            f'<rect x="1" y="1" width="{layout.panel_width}" height="{layout.height - 2}" '
            f'rx="10" fill="{theme.panel_bg}"/>'
        )
        divider = (
            f'<line x1="{layout.panel_width + 1}" y1="14" x2="{layout.panel_width + 1}" '
            f'y2="{layout.height - 14}" stroke="{theme.border}" stroke-width="1"/>'
        )
        return clip + card + panel + glow + divider
    return clip + card + glow


def _tier_panel(summary: CodemaruSummary, layout: _Layout, theme: Theme, token: str) -> str:
    scores = summary.scores
    cx = layout.panel_width / 2
    github = summary.input.github
    handle = truncate(github, 24 if layout.panel_width > 220 else 18)
    href = escape_xml(f"https://github.com/{github}")

    emblem = tier_emblem(
        layout.emblem_cx, layout.emblem_cy, layout.emblem_r, scores.tier, scores.overall, token
    )
    name = tier_nameplate(cx, layout.tier_name_y, scores.tier, layout.panel_width - 30, 31)
    caption = text_path(
        "TOP STRENGTHS",
        family=SANS,
        weight=500,
        size=9,
        x=cx,
        y=layout.caption_y,
        anchor="middle",
        fill=theme.muted,
        letter_spacing=1.8,
    )
    badges = _strength_badges(summary, layout, theme, token)
    handle_text = f"@{handle}"
    handle_w = text_width(handle_text, family=MONO, weight=500, size=12.5)
    underline = (
        f'<line x1="{fmt_num(cx - handle_w / 2)}" y1="{fmt_num(layout.handle_y + 2)}" '
        f'x2="{fmt_num(cx + handle_w / 2)}" y2="{fmt_num(layout.handle_y + 2)}" '
        f'stroke="{theme.text}" stroke-width="0.8"/>'
    )
    handle_link = (
        f'<a href="{href}" xlink:href="{href}" target="_blank" rel="noopener noreferrer">'
        + text_path(
            handle_text,
            family=MONO,
            weight=500,
            size=12.5,
            x=cx,
            y=layout.handle_y,
            anchor="middle",
            fill=theme.text,
        )
        + underline
        + "</a>"
    )
    wordmark = text_path(
        "codemaru",
        family=SANS,
        weight=500,
        size=10,
        x=cx,
        y=layout.wordmark_y,
        anchor="middle",
        fill=theme.muted,
        letter_spacing=2,
    )
    return f"<g>{emblem}{name}{caption}{badges}{handle_link}{wordmark}</g>"


def _strength_badges(summary: CodemaruSummary, layout: _Layout, theme: Theme, token: str) -> str:
    cx = layout.panel_width / 2
    strengths = summary.strengths[:3]
    count = len(strengths)
    offsets = [-1.0, 0.0, 1.0] if count == 3 else [i - (count - 1) / 2 for i in range(count)]
    out: list[str] = []
    for i, axis in enumerate(strengths):
        x = cx + offsets[i] * layout.trophy_spacing
        out.append(strength_badge(x, layout.trophy_cy, layout.trophy_scale, axis, i, token))
        out.append(
            text_path(
                truncate(AXIS_SHORT_LABELS[axis], 14),
                family=SANS,
                weight=500,
                size=8.5,
                x=x,
                y=layout.trophy_label_y,
                anchor="middle",
                fill=theme.muted,
            )
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
            + text_path(
                truncate(AXIS_LABELS[axis], 16),
                family=SANS,
                weight=500,
                size=10,
                x=lx,
                y=ly,
                anchor=anchor,
                fill=theme.muted,
            )
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
        cells.append(
            text_path(
                truncate(m.value, 12),
                family=MONO,
                weight=600,
                size=13,
                x=x,
                y=y,
                anchor="middle",
                fill=theme.text,
            )
            + text_path(
                truncate(m.label, 12),
                family=SANS,
                weight=500,
                size=10,
                x=x,
                y=y + 16,
                anchor="middle",
                fill=theme.muted,
            )
        )
    divider = (
        f'<line x1="{start_x}" y1="{fmt_num(y - 26)}" x2="{end_x}" y2="{fmt_num(y - 26)}" '
        f'stroke="{theme.border}" stroke-width="1"/>'
    )
    return f"<g>{divider}{''.join(cells)}</g>"


def _footer(summary: CodemaruSummary, layout: _Layout, theme: Theme) -> str:
    date = summary.updated_at.date().isoformat()
    # Prefer the more specific "stale data" (a last-good fallback) over the
    # generic "partial data" (one platform degraded this fetch).
    if summary.stale:
        flag = "stale data"
    elif summary.overall_status.value != "ok":
        flag = "partial data"
    else:
        flag = ""
    x = layout.panel_width + 16
    left = f"scoreVersion {truncate(summary.scores.score_version, 10)} · {date}"
    badge = (
        text_path(
            flag,
            family=SANS,
            weight=500,
            size=9,
            x=layout.width - 14,
            y=layout.footer_y,
            anchor="end",
            fill=theme.muted,
        )
        if flag
        else ""
    )
    return (
        text_path(
            left,
            family=MONO,
            weight=400,
            size=9,
            x=x,
            y=layout.footer_y,
            anchor="start",
            fill=theme.muted,
        )
        + badge
    )


def _animation_css() -> str:
    """A one-shot entrance animation for the tier emblem + nameplate, as a CSS
    ``<style>`` block embedded in the SVG.

    Declarative CSS animations run even when the SVG is referenced via ``<img>``
    (e.g. a GitHub README), where scripts are disabled. Crucially, content
    elements are never hidden by base styles — they only animate *from* a hidden
    keyframe with ``animation-fill-mode: both`` — so any renderer that ignores the
    ``<style>`` (or honours prefers-reduced-motion) still shows the complete card.

    The sequence mirrors the design spec: hex stamps in → score → wing-rest rises
    → wings swing in from each side → crown spikes rise left-to-right → apex gem
    drops → nameplate wipes in.
    """
    # Crown spikes exist only for Gold+ (up to 7); stagger them left-to-right.
    ray_delays = "".join(
        f".cm-rays>*:nth-child({i}){{animation-delay:{0.98 + (i - 1) * 0.055:.2f}s}}"
        for i in range(1, 8)
    )
    return (
        "<style>"
        "@keyframes cm-stamp{0%{opacity:0;transform:scale(1.5)}60%{opacity:1}"
        "100%{opacity:1;transform:scale(1)}}"
        "@keyframes cm-pop{0%{opacity:0;transform:translateY(4px)}"
        "100%{opacity:1;transform:translateY(0)}}"
        "@keyframes cm-rise{0%{opacity:0;transform:translateY(9px)}"
        "100%{opacity:1;transform:translateY(0)}}"
        "@keyframes cm-wing-l{0%{opacity:0;transform:rotate(-34deg)}"
        "100%{opacity:1;transform:rotate(0)}}"
        "@keyframes cm-wing-r{0%{opacity:0;transform:rotate(34deg)}"
        "100%{opacity:1;transform:rotate(0)}}"
        "@keyframes cm-ray{0%{opacity:0;transform:translateY(7px)}"
        "100%{opacity:1;transform:translateY(0)}}"
        "@keyframes cm-drop{0%{opacity:0;transform:translateY(-15px)}"
        "100%{opacity:1;transform:translateY(0)}}"
        "@keyframes cm-wipe{0%{clip-path:inset(0 100% 0 0)}100%{clip-path:inset(0 0 0 0)}}"
        ".cm-hex{animation:cm-stamp .4s cubic-bezier(.2,.8,.2,1.25) both;"
        "transform-box:fill-box;transform-origin:center}"
        ".cm-score{animation:cm-pop .25s ease-out .34s both}"
        ".cm-rest{animation:cm-rise .28s ease-out .54s both}"
        ".cm-wing-l{animation:cm-wing-l .4s cubic-bezier(.2,.7,.3,1) .7s both;"
        "transform-box:fill-box;transform-origin:bottom right}"
        ".cm-wing-r{animation:cm-wing-r .4s cubic-bezier(.2,.7,.3,1) .7s both;"
        "transform-box:fill-box;transform-origin:bottom left}"
        ".cm-rays>*{animation:cm-ray .28s ease-out both}"
        f"{ray_delays}"
        ".cm-apex{animation:cm-drop .3s ease-out 1.45s both}"
        ".cm-spark{animation:cm-pop .3s ease-out 1.55s both}"
        ".cm-name{animation:cm-wipe .4s ease-out 1.68s both}"
        "@media (prefers-reduced-motion:reduce){"
        ".cm-hex,.cm-score,.cm-rest,.cm-wing-l,.cm-wing-r,.cm-rays>*,.cm-apex,.cm-spark,"
        ".cm-name{animation:none}}"
        "</style>"
    )


def render_card(summary: CodemaruSummary, options: RenderOptions | None = None) -> str:
    """Render a full card SVG for the summary."""
    opts = options or RenderOptions()
    layout = _COMPACT if opts.compact else _DEFAULT
    theme = get_theme(opts.theme)
    token = id_token(f"{summary.input.github}:{summary.scores.tier.value}")

    style = _animation_css() if opts.animate else ""
    with glyph_defs() as glyphs:
        parts = [
            gradient_defs(summary.scores.tier, token),
            _background(layout, theme, token),
            _tier_panel(summary, layout, theme, token),
            _radar(summary, layout, theme),
            _metrics_row(summary, layout, theme),
            # Compact shows only the tier panel — no footer.
            "" if opts.compact else _footer(summary, layout, theme),
        ]
    return _svg_document(layout, summary, defs_markup(glyphs) + style + "".join(parts))


def render_error_card(message: str, options: RenderOptions | None = None) -> str:
    """A minimal error card so failures never return a blank/broken image."""
    opts = options or RenderOptions()
    layout = _COMPACT if opts.compact else _DEFAULT
    theme = get_theme(opts.theme)
    fill = "none" if theme.bg == "transparent" else theme.bg
    rect = (
        f'<rect x="0.5" y="0.5" width="{layout.width - 1}" height="{layout.height - 1}" '
        f'rx="10" fill="{fill}" stroke="{theme.border}"/>'
    )
    with glyph_defs() as glyphs:
        text = text_path(
            "codemaru",
            family=SANS,
            weight=700,
            size=16,
            x=layout.width / 2,
            y=layout.height / 2 - 8,
            anchor="middle",
            fill=theme.title,
        ) + text_path(
            truncate(message, 60),
            family=SANS,
            weight=400,
            size=12,
            x=layout.width / 2,
            y=layout.height / 2 + 16,
            anchor="middle",
            fill=theme.muted,
        )
    return _svg_document(layout, None, defs_markup(glyphs) + rect + text)


def _svg_document(layout: _Layout, summary: CodemaruSummary | None, body: str) -> str:
    if summary is not None:
        title = (
            f"codemaru card for {safe_text(summary.input.github, 39)} — {summary.scores.tier.value}"
        )
    else:
        title = "codemaru card"
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
        f'width="{layout.width}" height="{layout.height}" '
        f'viewBox="0 0 {layout.width} {layout.height}" role="img" aria-label="{title}">'
        f"<title>{title}</title>{body}</svg>"
    )
