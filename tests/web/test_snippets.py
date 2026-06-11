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
