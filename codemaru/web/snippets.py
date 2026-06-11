"""Builds the card query string and the copy-paste embed snippets shown in the
generator. Pure functions so they can be unit-tested without a browser."""

from __future__ import annotations

from urllib.parse import urlencode

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
    if profile.boj:
        params.append(("boj", profile.boj))
    if profile.leetcode:
        params.append(("leetcode", profile.leetcode))
    if options.theme is not ThemeName.DEFAULT:
        params.append(("theme", options.theme.value))
    if options.compact:
        params.append(("compact", "true"))
    # Animation is the default, so only the opt-out needs to ride in the URL.
    if not options.animate:
        params.append(("animate", "false"))
    return urlencode(params)


def build_snippets(base_url: str, profile: ProfileInput, options: RenderOptions) -> dict[str, str]:
    """Return cardUrl, markdown, picture, and action snippets for the given input."""
    query = build_card_query(profile, options)
    card_url = f"{base_url}/api/card.svg?{query}"
    alt = f"codemaru card for {profile.github}"

    markdown = f"[![{alt}]({card_url})](https://github.com/{profile.github})"
    picture = f'<picture>\n  <img alt="{alt}" src="{card_url}" />\n</picture>'

    # Mirror the same inputs as the preview so the static Action output matches
    # the dynamic card the user is looking at.
    with_lines = ["          github: ${{ github.repository_owner }}"]
    if profile.boj:
        with_lines.append(f"          boj: {profile.boj}")
    if profile.leetcode:
        with_lines.append(f"          leetcode: {profile.leetcode}")
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
