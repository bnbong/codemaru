"""Parse and validate card/summary query parameters into domain models.

Routes never touch raw query values directly — they call ``parse_request`` and
handle the single, friendly error message it raises.
"""

from __future__ import annotations

from pydantic import ValidationError

from codemaru.models.input import ProfileInput
from codemaru.models.render import RenderOptions, ThemeName

_TRUTHY = {"true", "1", "yes", "on"}
_FALSY = {"false", "0", "no", "off", ""}


class QueryError(ValueError):
    """Raised when query parameters fail validation; message is user-facing."""


def parse_request(
    github: str | None,
    boj: str | None,
    leetcode: str | None,
    theme: str | None,
    compact: str | None,
) -> tuple[ProfileInput, RenderOptions]:
    """Return (profile, options) or raise QueryError with a friendly message."""
    if not github or not github.strip():
        raise QueryError("github: a GitHub username is required")

    try:
        profile = ProfileInput(github=github, boj=boj, leetcode=leetcode)
    except ValidationError as exc:
        raise QueryError(_first_message(exc)) from exc

    theme_value = (theme or "default").strip().lower()
    try:
        theme_enum = ThemeName(theme_value)
    except ValueError as exc:
        raise QueryError("theme: must be one of default, dark, transparent") from exc

    compact_value = (compact or "").strip().lower()
    if compact_value in _TRUTHY:
        is_compact = True
    elif compact_value in _FALSY:
        is_compact = False
    else:
        raise QueryError("compact: must be true or false")
    return profile, RenderOptions(theme=theme_enum, compact=is_compact)


def _first_message(exc: ValidationError) -> str:
    error = exc.errors()[0]
    field = ".".join(str(p) for p in error.get("loc", ())) or "query"
    msg = error.get("msg", "invalid value")
    # Strip pydantic's "Value error, " prefix for a cleaner message.
    msg = msg.removeprefix("Value error, ")
    return f"{field}: {msg}"
