from codemaru.models.input import ProfileInput
from codemaru.models.render import RenderOptions, ThemeName
from codemaru.web.snippets import build_card_query, build_snippets


def test_query_omits_defaults_and_empty_handles():
    qs = build_card_query(ProfileInput(github="octocat"), RenderOptions())
    assert qs == "github=octocat"


def test_query_includes_non_default_options():
    qs = build_card_query(
        ProfileInput(github="octocat", boj="baek"),
        RenderOptions(theme=ThemeName.DARK, compact=True),
    )
    assert "theme=dark" in qs
    assert "compact=true" in qs
    assert "boj=baek" in qs


def test_query_default_animate_is_omitted_optout_is_explicit():
    # Animation is on by default, so a clean URL means it's on.
    on = build_card_query(ProfileInput(github="octocat"), RenderOptions())
    assert "animate" not in on
    off = build_card_query(ProfileInput(github="octocat"), RenderOptions(animate=False))
    assert "animate=false" in off


def test_snippets_contain_card_url_and_markdown():
    snippets = build_snippets(
        "https://codemaru.dev", ProfileInput(github="octocat"), RenderOptions()
    )
    assert snippets["card_url"] == "https://codemaru.dev/api/card.svg?github=octocat"
    assert "![codemaru card for octocat]" in snippets["markdown"]
    assert "<picture>" in snippets["picture"]


def test_picture_pairs_a_dark_source_with_a_light_img():
    snippets = build_snippets(
        "https://codemaru.dev", ProfileInput(github="octocat"), RenderOptions()
    )
    assert snippets["picture"] == (
        "<picture>\n"
        '  <source media="(prefers-color-scheme: dark)"'
        ' srcset="https://codemaru.dev/api/card.svg?github=octocat&theme=dark" />\n'
        '  <img alt="codemaru card for octocat"'
        ' src="https://codemaru.dev/api/card.svg?github=octocat" />\n'
        "</picture>"
    )


def test_picture_source_and_img_differ_only_in_theme():
    snippets = build_snippets(
        "https://codemaru.dev",
        ProfileInput(github="octocat", boj="baek", leetcode="lc"),
        RenderOptions(compact=True, animate=False),
    )
    picture = snippets["picture"]
    handles = "github=octocat&boj=baek&leetcode=lc"
    rest = "compact=true&animate=false"
    assert f'srcset="https://codemaru.dev/api/card.svg?{handles}&theme=dark&{rest}"' in picture
    assert f'src="https://codemaru.dev/api/card.svg?{handles}&{rest}"' in picture


def test_picture_img_falls_back_to_default_when_dark_is_selected():
    # A dark <source> plus a dark <img> would be the same card twice, so the
    # fallback swaps to the light theme. Markdown keeps the user's selection.
    snippets = build_snippets(
        "https://codemaru.dev",
        ProfileInput(github="octocat"),
        RenderOptions(theme=ThemeName.DARK),
    )
    picture = snippets["picture"]
    assert 'srcset="https://codemaru.dev/api/card.svg?github=octocat&theme=dark"' in picture
    assert 'src="https://codemaru.dev/api/card.svg?github=octocat"' in picture
    assert "theme=dark" in snippets["markdown"]


def test_picture_keeps_transparent_on_the_img():
    snippets = build_snippets(
        "https://codemaru.dev",
        ProfileInput(github="octocat"),
        RenderOptions(theme=ThemeName.TRANSPARENT),
    )
    picture = snippets["picture"]
    transparent = "https://codemaru.dev/api/card.svg?github=octocat&theme=transparent"
    assert 'srcset="https://codemaru.dev/api/card.svg?github=octocat&theme=dark"' in picture
    assert f'src="{transparent}"' in picture


def test_action_snippet_reflects_theme_and_compact():
    snippets = build_snippets(
        "https://codemaru.dev",
        ProfileInput(github="octocat", boj="baek"),
        RenderOptions(theme=ThemeName.DARK, compact=True),
    )
    action = snippets["action"]
    assert "uses: bnbong/codemaru@v1" in action
    assert "theme: dark" in action
    assert "compact: true" in action
    assert "boj: baek" in action


def test_action_snippet_omits_defaults():
    snippets = build_snippets(
        "https://codemaru.dev", ProfileInput(github="octocat"), RenderOptions()
    )
    assert "theme:" not in snippets["action"]
    assert "compact:" not in snippets["action"]
    assert "animate:" not in snippets["action"]  # animation on by default


def test_action_snippet_includes_animate_opt_out():
    snippets = build_snippets(
        "https://codemaru.dev", ProfileInput(github="octocat"), RenderOptions(animate=False)
    )
    assert "animate: false" in snippets["action"]


def test_query_carries_jungol_in_registry_order():
    # Registry order is the URL's order, and jungol is appended last so existing
    # links keep their exact shape.
    qs = build_card_query(
        ProfileInput(github="octocat", boj="baek", leetcode="lc", jungol="jo"), RenderOptions()
    )
    assert qs == "github=octocat&boj=baek&leetcode=lc&jungol=jo"


def test_query_omits_jungol_when_it_is_not_supplied():
    qs = build_card_query(ProfileInput(github="octocat", boj="baek"), RenderOptions())
    assert "jungol" not in qs


def test_snippets_carry_jungol_into_markdown_picture_and_action():
    snippets = build_snippets(
        "https://codemaru.dev",
        ProfileInput(github="octocat", jungol="jo"),
        RenderOptions(),
    )
    assert "jungol=jo" in snippets["card_url"]
    assert "jungol=jo" in snippets["markdown"]
    assert snippets["picture"].count("jungol=jo") == 2  # the dark source and the img
    assert "          jungol: jo" in snippets["action"]
