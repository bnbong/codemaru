"""Golden SHA-256 digests of the demo-fixture cards.

Card text is outlined to paths from pinned static font instances, so a render is
byte-deterministic: the same summary always produces the same SVG. That makes a
hash a cheap, total regression guard — any accidental change to layout, palette,
animation CSS or font loading moves it.

After an *intentional* change, review the rendered diff and then refresh the
digests with::

    uv run python -m tests.render.golden --update
"""

from __future__ import annotations

import hashlib
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

from codemaru.core.summary import build_summary
from codemaru.fixtures.demo import DEMO_INPUT, full_bundle
from codemaru.models.render import RenderOptions, ThemeName
from codemaru.render import render_card, render_error_card

TIMESTAMP = datetime(2026, 5, 31, tzinfo=UTC)
ERROR_MESSAGE = "github: invalid handle"
UPDATE_COMMAND = "uv run python -m tests.render.golden --update"

GOLDEN = {
    # --- begin golden digests ---
    "default": "d854c5a8b225afb89ae9af0bcfd988a88f8e6d4aef3bf21d9e1fe5fa6dffb9af",
    "dark": "4dbffcb6210a26154b3f1ee354e263961d520bdc1dd56c37238b5b53d58149d0",
    "transparent": "e3a68a80087e1acf0a2998b75acb2e6e8eeb47b224826ce697f7fc8385e752d0",
    "compact": "d2d67456dadd43bc0dbe54b42545d8d2f374a5b1916afb36def14f34ea6bf696",
    "error": "eb77e88a6eb46326c6b527a584e26644ce0f624d39e767522bc173c7a8b487ca",
    # --- end golden digests ---
}


def render_variants() -> dict[str, str]:
    """Render the five reference SVGs from the demo fixture at a fixed timestamp."""
    summary = build_summary(DEMO_INPUT, full_bundle(), TIMESTAMP)
    return {
        "default": render_card(summary, RenderOptions(animate=True)),
        "dark": render_card(summary, RenderOptions(theme=ThemeName.DARK, animate=True)),
        "transparent": render_card(
            summary, RenderOptions(theme=ThemeName.TRANSPARENT, animate=True)
        ),
        "compact": render_card(summary, RenderOptions(compact=True, animate=True)),
        "error": render_error_card(ERROR_MESSAGE),
    }


def digests() -> dict[str, str]:
    """SHA-256 of each reference SVG, keyed the same way as GOLDEN."""
    return {
        name: hashlib.sha256(svg.encode("utf-8")).hexdigest()
        for name, svg in render_variants().items()
    }


def _update() -> int:
    """Rewrite the GOLDEN block in this file with freshly rendered digests."""
    path = Path(__file__)
    body = "".join(f'    "{name}": "{d}",\n' for name, d in digests().items())
    new = re.sub(
        r"(    # --- begin golden digests ---\n).*?(    # --- end golden digests ---\n)",
        lambda m: m.group(1) + body + m.group(2),
        path.read_text(encoding="utf-8"),
        flags=re.DOTALL,
    )
    path.write_text(new, encoding="utf-8")
    print(f"updated {len(GOLDEN)} golden digests in {path}")
    return 0


if __name__ == "__main__":
    if sys.argv[1:] != ["--update"]:
        print(f"usage: {UPDATE_COMMAND}", file=sys.stderr)
        raise SystemExit(2)
    raise SystemExit(_update())
