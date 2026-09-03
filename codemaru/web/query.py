"""Parse and validate card/summary query parameters into domain models.

Routes never touch raw query values directly — they call ``parse_request`` and
handle the single, friendly error message it raises.
"""

from __future__ import annotations

from pydantic import ValidationError

from codemaru.adapters.registry import JUDGES
from codemaru.models.input import ProfileInput
from codemaru.models.render import RenderOptions, ThemeName

_TRUTHY = {"true", "1", "yes", "on"}
_FALSY = {"false", "0", "no", "off", ""}


class QueryError(ValueError):
    """Raised when query parameters fail validation; message is user-facing."""


def parse_request(
    github: str | None,
    boj: str | None = None,
    leetcode: str | None = None,
    jungol: str | None = None,
    theme: str | None = None,
    compact: str | None = None,
    animate: str | None = None,
) -> tuple[ProfileInput, RenderOptions]:
    """Return (profile, options) or raise QueryError with a friendly message."""
    if not github or not github.strip():
        raise QueryError("github: a GitHub username is required")

    # The judge params stay explicit in the signature (they mirror the public
    # query contract, which FastAPI also declares by name), but the profile is
    # assembled by walking the registry so a new judge flows through unchanged.
    # A new judge is appended in registry order, which shifts the positions after
    # it — so callers pass everything but ``github`` by keyword.
    supplied = {"boj": boj, "leetcode": leetcode, "jungol": jungol}
    handles = {p.param: supplied.get(p.param) for p in JUDGES}
    try:
        profile = ProfileInput(github=github, **handles)
    except ValidationError as exc:
        raise QueryError(_first_message(exc)) from exc

    theme_value = (theme or "default").strip().lower()
    try:
        theme_enum = ThemeName(theme_value)
    except ValueError as exc:
        raise QueryError("theme: must be one of default, dark, transparent") from exc

    is_compact = _parse_bool(compact, field="compact", default=False)
    # Animation is on by default; an absent param keeps it on.
    is_animate = _parse_bool(animate, field="animate", default=True)
    return profile, RenderOptions(theme=theme_enum, compact=is_compact, animate=is_animate)


def _parse_bool(value: str | None, *, field: str, default: bool) -> bool:
    normalized = (value or "").strip().lower()
    if value is None or normalized == "":
        return default
    if normalized in _TRUTHY:
        return True
    if normalized in _FALSY:
        return False
    raise QueryError(f"{field}: must be true or false")


def _first_message(exc: ValidationError) -> str:
    error = exc.errors()[0]
    field = ".".join(str(p) for p in error.get("loc", ())) or "query"
    msg = error.get("msg", "invalid value")
    # Strip pydantic's "Value error, " prefix for a cleaner message.
    msg = msg.removeprefix("Value error, ")
    return f"{field}: {msg}"
