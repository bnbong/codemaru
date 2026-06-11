"""Options that control how a CodemaruSummary is rendered to SVG."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel


class ThemeName(StrEnum):
    DEFAULT = "default"
    DARK = "dark"
    TRANSPARENT = "transparent"


class RenderOptions(BaseModel):
    theme: ThemeName = ThemeName.DEFAULT
    # Compact drops the radar and metric row, leaving the tier panel only.
    compact: bool = False
    # Embed a one-shot entrance animation (CSS @keyframes) for the tier emblem and
    # nameplate. On by default; `animate=false` ships a static card. Respects
    # prefers-reduced-motion and degrades to the static card where CSS is ignored.
    animate: bool = True


DEFAULT_RENDER_OPTIONS = RenderOptions()
