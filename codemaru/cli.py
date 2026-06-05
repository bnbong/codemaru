"""Command-line interface for static card generation.

``codemaru generate --github <user> --out profile/codemaru.svg`` runs the live
adapters and writes a self-contained SVG to disk — the same scoring/render path
as the hosted API, but without needing the Vercel service. This is what the
GitHub Action (``action.yml``) invokes so users can commit a freshly generated
card into their own repository on a schedule.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

from codemaru.render import render_card
from codemaru.web.query import QueryError, parse_request


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="codemaru", description="codemaru card generator")
    sub = parser.add_subparsers(dest="command", required=True)

    gen = sub.add_parser("generate", help="render a card SVG to a file")
    gen.add_argument("--github", required=True, help="GitHub username")
    gen.add_argument("--boj", default=None, help="solved.ac / BOJ handle")
    gen.add_argument("--leetcode", default=None, help="LeetCode handle")
    gen.add_argument("--theme", default="default", help="default | dark | transparent")
    gen.add_argument("--compact", action="store_true", help="compact layout (tier panel only)")
    gen.add_argument("--out", required=True, help="output path for the generated SVG")
    return parser


async def _generate(args: argparse.Namespace) -> int:
    # Static generation is always live — serving fixtures here would defeat the
    # purpose. Force it on, then drop the cached Settings so the override applies
    # even if some import read settings earlier in the process.
    os.environ["FIXTURE_MODE"] = "false"
    from codemaru.settings import get_settings

    get_settings.cache_clear()

    from codemaru.service import LiveDataUnavailableError, get_summary

    try:
        profile, options = parse_request(
            args.github,
            args.boj,
            args.leetcode,
            args.theme,
            "true" if args.compact else "false",
        )
    except QueryError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    try:
        summary = await get_summary(profile)
    except LiveDataUnavailableError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    svg = render_card(summary, options)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(svg, encoding="utf-8")

    status = summary.overall_status.value
    print(f"wrote {out} ({len(svg)} bytes, status={status})")
    if status != "ok":
        # A degraded card still gets written (better than a failed workflow), but
        # surface it so the user can check tokens/handles.
        print(
            f"warning: card is degraded (status={status}); "
            "check GITHUB_TOKEN and the handles you passed",
            file=sys.stderr,
        )
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.command == "generate":
        return asyncio.run(_generate(args))
    return 2  # pragma: no cover - argparse enforces a valid subcommand


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
