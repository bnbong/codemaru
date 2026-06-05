import re
from datetime import UTC, datetime

from codemaru.core.summary import build_summary
from codemaru.fixtures.demo import DEMO_INPUT, full_bundle, github_fixture
from codemaru.models.input import ProfileInput
from codemaru.models.render import RenderOptions, ThemeName
from codemaru.models.snapshot import SnapshotBundle
from codemaru.render import render_card, render_error_card
from codemaru.render.xml import escape_xml, safe_text

_TS = datetime(2026, 5, 31, tzinfo=UTC)


def _summary():
    return build_summary(DEMO_INPUT, full_bundle(), _TS)


def test_escape_xml_handles_all_five():
    assert escape_xml("<a href=\"x\" data='y'>&") == (
        "&lt;a href=&quot;x&quot; data=&apos;y&apos;&gt;&amp;"
    )


def test_safe_text_truncates_and_escapes():
    assert safe_text("abcdef", 4) == "abc…"
    assert safe_text("<b>", 10) == "&lt;b&gt;"


def test_card_is_wellformed_svg():
    svg = render_card(_summary())
    assert svg.startswith("<svg")
    assert svg.rstrip().endswith("</svg>")
    assert 'xmlns="http://www.w3.org/2000/svg"' in svg
    assert 'viewBox="0 0 640 300"' in svg


def test_card_loads_no_external_subresources():
    # The card must not pull external sub-resources (GitHub's image sandbox blocks
    # them). The tier nameplate is inlined as a data: URI, and the only http(s)
    # hrefs are the GitHub profile *link* on the handle — not resource loads.
    svg = render_card(_summary())
    assert "<script" not in svg
    assert "<image" in svg  # nameplate is present...
    assert 'href="data:image/png;base64,' in svg  # ...and inlined, not external
    external = re.findall(r'href="(https?://[^"]+)"', svg)
    assert external  # the handle link exists
    assert all(url.startswith("https://github.com/") for url in external)


def test_default_card_shows_all_five_axes():
    svg = render_card(_summary())
    for label in ["Open Source", "Impact", "Consistency", "Problem Solving", "Depth"]:
        assert f">{label}<" in svg


def test_compact_drops_radar_metrics_and_footer():
    svg = render_card(_summary(), RenderOptions(compact=True))
    assert 'viewBox="0 0 250 256"' in svg
    assert ">Problem Solving<" not in svg
    assert "scoreVersion" not in svg
    assert "2026-05-31" not in svg
    assert 'fill="url(#emblem-' in svg


def test_card_does_not_show_confidence():
    assert "confidence" not in render_card(_summary())


def test_compact_renders_three_strength_badges():
    svg = render_card(_summary(), RenderOptions(compact=True))
    assert "TOP STRENGTHS" in svg
    short = ["Open Source", "Impact", "Consistency", "Solving", "Depth"]
    assert sum(1 for label in short if f">{label}<" in svg) == 3
    # medal-tinted glyph tiles use per-rank gradient ids
    assert "url(#tile-" in svg


def test_malicious_handle_is_escaped():
    evil = '"><script>alert(1)</script>'
    summary = build_summary(
        ProfileInput.model_construct(github=evil),
        SnapshotBundle(github=github_fixture().model_copy(update={"login": evil})),
        _TS,
    )
    svg = render_card(summary)
    assert "<script>" not in svg
    assert "&lt;script&gt;" in svg


def test_themes_change_background():
    dark = render_card(_summary(), RenderOptions(theme=ThemeName.DARK))
    transparent = render_card(_summary(), RenderOptions(theme=ThemeName.TRANSPARENT))
    assert "#0d1117" in dark
    assert 'fill="none"' in transparent


def test_error_card_is_valid_and_escaped():
    svg = render_error_card("github: invalid handle")
    assert svg.startswith("<svg")
    assert "codemaru" in svg
    assert "github: invalid handle" in svg
