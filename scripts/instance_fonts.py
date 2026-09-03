"""Pre-instance the variable fonts into the static TTFs the card renderer loads.

Instancing a variable font costs ~200 ms per (family, weight); a default card
needs five of them, so a serverless cold start used to spend ~1 s inside
fontTools before emitting a single glyph. Doing the instancing here — at
development time — and shipping the results as package assets turns that into a
couple of milliseconds of file reads.

Usage::

    uv run python scripts/instance_fonts.py            # (re)generate the assets
    uv run python scripts/instance_fonts.py --check     # fail if they're stale

``--check`` regenerates into a temp dir and diffs against the shipped files, so
CI catches a STATIC_INSTANCES edit that nobody regenerated. The variable TTFs
and both OFL licenses stay in place: the fallback path still needs the variable
fonts, and the licenses cover these derived instances too.
"""

from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

from fontTools.ttLib import TTFont
from fontTools.varLib import instancer

from codemaru.render.glyphs import STATIC_INSTANCES, static_path, variable_path


def _build(family: str, weight: int, dest: Path) -> None:
    """Instance ``family`` at ``weight`` and save the static TTF to ``dest``."""
    # recalcTimestamp=False keeps head.modified at the variable font's own date,
    # so regenerating produces byte-identical files and --check stays meaningful.
    font = TTFont(variable_path(family), recalcTimestamp=False)
    axis = next(a for a in font["fvar"].axes if a.axisTag == "wght")
    w = max(axis.minValue, min(axis.maxValue, float(weight)))
    if w != float(weight):
        raise SystemExit(
            f"weight {weight} is outside {family}'s wght axis "
            f"[{axis.minValue:g}, {axis.maxValue:g}] — it would clamp to {w:g}"
        )
    inst = instancer.instantiateVariableFont(font, {"wght": w}, inplace=False)
    dest.parent.mkdir(parents=True, exist_ok=True)
    inst.save(dest)


def generate() -> int:
    """Write every static instance into the package assets; return 0."""
    for family, weight in STATIC_INSTANCES:
        dest = static_path(family, weight)
        _build(family, weight, dest)
        print(f"{dest.name:<24} {dest.stat().st_size:>8,} bytes")
    total = sum(static_path(f, w).stat().st_size for f, w in STATIC_INSTANCES)
    print(f"{len(STATIC_INSTANCES)} instances, {total:,} bytes total")
    return 0


def check() -> int:
    """Diff freshly built instances against the shipped ones; return 1 if stale."""
    stale: list[str] = []
    with tempfile.TemporaryDirectory() as tmp:
        for family, weight in STATIC_INSTANCES:
            shipped = static_path(family, weight)
            fresh = Path(tmp) / shipped.name
            _build(family, weight, fresh)
            if not shipped.is_file():
                stale.append(f"{shipped.name}: missing")
            elif shipped.read_bytes() != fresh.read_bytes():
                stale.append(
                    f"{shipped.name}: differs "
                    f"({shipped.stat().st_size:,} vs {fresh.stat().st_size:,} bytes)"
                )
    if stale:
        print("static font instances are stale:", file=sys.stderr)
        for line in stale:
            print(f"  {line}", file=sys.stderr)
        print("regenerate with: uv run python scripts/instance_fonts.py", file=sys.stderr)
        return 1
    print(f"{len(STATIC_INSTANCES)} static instances up to date")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--check",
        action="store_true",
        help="verify the shipped instances match a fresh build instead of writing",
    )
    args = parser.parse_args(argv)
    return check() if args.check else generate()


if __name__ == "__main__":
    raise SystemExit(main())
