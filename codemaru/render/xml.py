"""Low-level SVG string helpers. All user-derived text MUST pass through
``escape_xml`` (or ``safe_text``) before entering the document — this is the
primary defense against query params breaking out of the SVG."""

from __future__ import annotations


def escape_xml(text: str) -> str:
    """Escape the five XML-significant characters."""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


def truncate(text: str, max_chars: int) -> str:
    """Hard-truncate a string (with an ellipsis) so it never overflows its box.

    ``max_chars`` is an approximate character cap (not pixel width) but adequate
    for the fixed-width label slots on the card. No XML escaping — use this when
    the text is rendered as vector outlines (paths), not as ``<text>`` content.
    """
    if len(text) > max_chars:
        text = text[: max(0, max_chars - 1)] + "…"
    return text


def safe_text(text: str, max_chars: int) -> str:
    """Escape and hard-truncate a string so text never overflows its box."""
    return escape_xml(truncate(text, max_chars))


def fmt_num(value: float) -> str:
    """Format a coordinate to at most 2 decimals (keeps SVG output compact)."""
    rounded = round(value * 100) / 100
    if rounded == int(rounded):
        return str(int(rounded))
    return f"{rounded:g}"
