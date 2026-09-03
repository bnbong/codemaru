"""Builds the card query string and the copy-paste embed snippets shown in the
generator. Pure functions so they can be unit-tested without a browser."""

from __future__ import annotations

from urllib.parse import urlencode

from codemaru.adapters.registry import JUDGES
from codemaru.models.input import ProfileInput
from codemaru.models.render import RenderOptions, ThemeName

# The GitHub Action (bnbong/codemaru, defined by action.yml) is published, so the
# generator shows the workflow snippet as a copyable, ready-to-use option.
ACTION_AVAILABLE = True


def build_card_query(profile: ProfileInput, options: RenderOptions) -> str:
    """Build the `?github=...` query string for the card endpoints.

    Default options and empty optional handles are omitted to keep URLs clean.
    """
    params: list[tuple[str, str]] = [("github", profile.github)]
    for platform in JUDGES:
        handle = profile.handle_for(platform.param)
        if handle:
            params.append((platform.param, handle))
    if options.theme is not ThemeName.DEFAULT:
        params.append(("theme", options.theme.value))
    if options.compact:
        params.append(("compact", "true"))
    # Animation is the default, so only the opt-out needs to ride in the URL.
    if not options.animate:
        params.append(("animate", "false"))
    return urlencode(params)


def _card_url(
    base_url: str, profile: ProfileInput, options: RenderOptions, theme: ThemeName
) -> str:
    """Card URL for the same inputs with only the theme swapped."""
    swapped = RenderOptions(theme=theme, compact=options.compact, animate=options.animate)
    return f"{base_url}/api/card.svg?{build_card_query(profile, swapped)}"


def build_snippets(base_url: str, profile: ProfileInput, options: RenderOptions) -> dict[str, str]:
    """Return cardUrl, markdown, picture, and action snippets for the given input."""
    query = build_card_query(profile, options)
    card_url = f"{base_url}/api/card.svg?{query}"
    alt = f"codemaru card for {profile.github}"

    markdown = f"[![{alt}]({card_url})](https://github.com/{profile.github})"

    # <picture> pairs a dark-scheme <source> with a light <img> fallback, so the
    # embed follows the reader's GitHub theme. Every other param (compact,
    # animate, handles) is identical between the two. When the user already picked
    # `dark`, the <img> falls back to `default` so the pair really is light/dark;
    # `transparent` is kept on the <img> because it suits either scheme.
    dark_url = _card_url(base_url, profile, options, ThemeName.DARK)
    img_theme = ThemeName.DEFAULT if options.theme is ThemeName.DARK else options.theme
    img_url = _card_url(base_url, profile, options, img_theme)
    picture = (
        "<picture>\n"
        f'  <source media="(prefers-color-scheme: dark)" srcset="{dark_url}" />\n'
        f'  <img alt="{alt}" src="{img_url}" />\n'
        "</picture>"
    )

    # Mirror the same inputs as the preview so the static Action output matches
    # the dynamic card the user is looking at.
    with_lines = ["          github: ${{ github.repository_owner }}"]
    for platform in JUDGES:
        handle = profile.handle_for(platform.param)
        if handle:
            with_lines.append(f"          {platform.param}: {handle}")
    if options.theme is not ThemeName.DEFAULT:
        with_lines.append(f"          theme: {options.theme.value}")
    if options.compact:
        with_lines.append("          compact: true")
    if not options.animate:
        with_lines.append("          animate: false")
    with_lines.append("          out: profile/codemaru.svg")
    with_block = "\n".join(with_lines)

    action = (
        "name: Update codemaru card\n"
        "on:\n"
        "  schedule:\n"
        '    - cron: "0 3 * * *"\n'
        "  workflow_dispatch:\n"
        "jobs:\n"
        "  update:\n"
        "    runs-on: ubuntu-latest\n"
        "    permissions:\n"
        "      contents: write\n"
        "    steps:\n"
        "      - uses: actions/checkout@v4\n"
        "      - uses: bnbong/codemaru@v1\n"
        "        with:\n"
        f"{with_block}\n"
        "      - run: |\n"
        '          git config user.name "github-actions"\n'
        '          git config user.email "github-actions@users.noreply.github.com"\n'
        "          git add profile/codemaru.svg\n"
        '          git commit -m "Update codemaru card" || exit 0\n'
        "          git push"
    )

    return {"card_url": card_url, "markdown": markdown, "picture": picture, "action": action}
