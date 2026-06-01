import pytest
from pydantic import ValidationError

from codemaru.models.input import ProfileInput
from codemaru.models.render import RenderOptions, ThemeName


@pytest.mark.parametrize("good", ["octocat", "foo-bar", "a", "codemaru-demo"])
def test_valid_github_usernames(good):
    assert ProfileInput(github=good).github == good


@pytest.mark.parametrize("bad", ["foo_bar", "foo.bar", "-foo", "foo-", "a b", '"><svg>'])
def test_invalid_github_usernames(bad):
    with pytest.raises(ValidationError):
        ProfileInput(github=bad)


def test_platform_handles_allow_underscore_and_dot():
    profile = ProfileInput(github="octocat", boj="foo_bar", leetcode="foo.bar")
    assert profile.boj == "foo_bar"
    assert profile.leetcode == "foo.bar"


def test_blank_optional_handles_become_none():
    profile = ProfileInput(github="octocat", boj="   ", leetcode="")
    assert profile.boj is None
    assert profile.leetcode is None


def test_render_options_defaults_and_theme_enum():
    opts = RenderOptions()
    assert opts.theme is ThemeName.DEFAULT
    assert opts.compact is False
    with pytest.raises(ValidationError):
        RenderOptions(theme="neon")  # type: ignore[arg-type]
