"""Structured logging: one JSON object per line, on stdout.

codemaru runs as a serverless function, so stdout *is* the observability surface
— Vercel ingests each line and indexes the JSON, which turns "this card is slow"
into a query over ``event`` / ``platform`` / ``ms`` instead of a guess.

Two rules hold everywhere:

* **Only public handles.** GitHub logins and judge handles are already visible on
  the card and in its URL. Request headers, viewer IPs and tokens are never
  logged. A caught exception whose message may carry a secret contributes its
  class name only — ``kv_error`` is the case that matters, since a KV error
  string embeds the credentialed REST URL. The one deliberate exception is the
  card route's catch-all, which logs the full traceback via ``log_exception``:
  the viewer is shown "temporarily unavailable", so this is the only place an
  unexpected bug ever surfaces, and it handles no credentialed URLs.
* **Telemetry never breaks a card.** Every entry point swallows its own errors,
  and the expensive part (serialization) is skipped entirely when the logger is
  disabled, which is the default outside a configured app.
"""

from __future__ import annotations

import contextlib
import json
import logging
import sys
from time import monotonic
from typing import Any

logger = logging.getLogger("codemaru")

# Marks a record whose message is already a complete JSON object, so the
# formatter passes it through instead of wrapping it again.
_STRUCTURED = "codemaru_structured"


def elapsed_ms(started: float) -> float:
    """Milliseconds since a ``time.monotonic()`` mark, rounded for readability."""
    return round((monotonic() - started) * 1000, 1)


def _encode(event: str, fields: dict[str, Any]) -> str:
    """Serialize one event to a single-line JSON object.

    ``default=str`` is the safety net: an unexpected value (a datetime, a model)
    degrades to its repr rather than raising on the hot path.
    """
    return json.dumps({"event": event, **fields}, default=str, separators=(",", ":"))


def log_event(event: str, **fields: Any) -> None:
    """Emit one JSON line describing ``event``.

    A no-op when the logger is disabled — the guard runs before serialization, so
    an unconfigured process pays nothing per card build.
    """
    if not logger.isEnabledFor(logging.INFO):
        return
    with contextlib.suppress(Exception):  # observability must never break a card
        logger.info(_encode(event, fields), extra={_STRUCTURED: True})


def log_exception(event: str, **fields: Any) -> None:
    """Like ``log_event``, but attaches the traceback of the exception in flight.

    Only valid inside an ``except`` block. The formatter splices the traceback
    into the same JSON object under ``error``, so the line stays parseable.
    """
    if not logger.isEnabledFor(logging.ERROR):
        return
    with contextlib.suppress(Exception):  # observability must never break a card
        logger.exception(_encode(event, fields), extra={_STRUCTURED: True})


def log_adapter(
    platform: str, handle: str, *, status: str, note: str | None, started: float
) -> None:
    """One line per adapter return: which platform, whose handle, how it went.

    Emitted on every path, success or degradation, so the ratio of ``ok`` to
    ``unavailable`` per platform is directly measurable.
    """
    log_event(
        "adapter",
        platform=platform,
        handle=handle,
        status=status,
        ms=elapsed_ms(started),
        note=note,
    )


class JsonLineFormatter(logging.Formatter):
    """Render every record as one JSON object.

    Records from ``log_event`` already carry a complete JSON object as their
    message and pass through verbatim — that is what makes them queryable.
    Anything else (a library warning, a bare ``logger.exception``) is wrapped in
    a minimal envelope so the stream never mixes formats.
    """

    def format(self, record: logging.LogRecord) -> str:
        message = record.getMessage()
        structured = getattr(record, _STRUCTURED, False)
        if structured and record.exc_info is None:
            return message

        payload: dict[str, Any]
        if structured:
            try:
                payload = json.loads(message)
            except ValueError:  # pragma: no cover - _encode always yields an object
                payload = {"event": "log", "message": message}
        else:
            payload = {
                "event": "log",
                "level": record.levelname,
                "logger": record.name,
                "message": message,
            }
        if record.exc_info is not None:
            payload["error"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str, separators=(",", ":"))


def configure_logging() -> None:
    """Enable our logger, and attach a stdout JSON handler if nothing else owns
    logging.

    Called from ``create_app()`` and the CLI entry point.

    Only the *handler* is conditional: a root logger that already has handlers
    belongs to someone else (uvicorn, pytest, Vercel's runtime), and adding a
    second one would duplicate every line. The level is set unconditionally —
    ``log_event`` short-circuits on ``isEnabledFor(INFO)``, so returning early
    without it silently dropped every event on exactly those hosts. Setting it on
    our logger only leaves the root level governing third-party libraries, so
    this never turns on httpx's per-request chatter.

    Failing to configure logging is never worth crashing over.
    """
    with contextlib.suppress(Exception):  # observability must never break startup
        logger.setLevel(logging.INFO)
        root = logging.getLogger()
        if root.handlers:
            return
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(JsonLineFormatter())
        root.addHandler(handler)
