"""Theme tokens. Every color used by the renderer comes from one of these tokens
— no hard-coded colors in layout code."""

from __future__ import annotations

from dataclasses import dataclass

from codemaru.models.render import ThemeName
from codemaru.models.score import Tier


@dataclass(frozen=True)
class Theme:
    bg: str
    border: str
    panel_bg: str
    title: str
    text: str
    muted: str
    accent: str
    grid: str
    radar_fill: str
    radar_stroke: str


_DEFAULT = Theme(
    bg="#ffffff",
    border="#e1e4e8",
    panel_bg="#f6f8fa",
    title="#1f2328",
    text="#1f2328",
    muted="#656d76",
    accent="#0969da",
    grid="#d0d7de",
    radar_fill="rgba(9,105,218,0.20)",
    radar_stroke="#0969da",
)

_DARK = Theme(
    bg="#0d1117",
    border="#30363d",
    panel_bg="#161b22",
    title="#e6edf3",
    text="#e6edf3",
    muted="#8b949e",
    accent="#58a6ff",
    grid="#30363d",
    radar_fill="rgba(88,166,255,0.22)",
    radar_stroke="#58a6ff",
)

_TRANSPARENT = Theme(
    bg="transparent",
    border="#30363d",
    panel_bg="rgba(127,127,127,0.08)",
    title="#e6edf3",
    text="#e6edf3",
    muted="#8b949e",
    accent="#58a6ff",
    grid="#30363d",
    radar_fill="rgba(88,166,255,0.22)",
    radar_stroke="#58a6ff",
)

_THEMES: dict[ThemeName, Theme] = {
    ThemeName.DEFAULT: _DEFAULT,
    ThemeName.DARK: _DARK,
    ThemeName.TRANSPARENT: _TRANSPARENT,
}


def get_theme(name: ThemeName) -> Theme:
    return _THEMES.get(name, _DEFAULT)


# Tier accent colors, used for emblem stroke and tier name.
TIER_COLORS: dict[Tier, str] = {
    Tier.SEED: "#8b949e",
    Tier.BRONZE: "#cd7f32",
    Tier.SILVER: "#9ca3af",
    Tier.GOLD: "#d4af37",
    Tier.PLATINUM: "#3fb6c4",
    Tier.DIAMOND: "#4aa8ff",
    Tier.MASTER: "#a371f7",
    Tier.MARU: "#f778ba",
}

# Emblem fill gradient (top -> bottom) per tier: a brighter highlight falling to
# a saturated base, so the badge reads like a game rank emblem.
TIER_GRADIENTS: dict[Tier, tuple[str, str]] = {
    Tier.SEED: ("#aeb6bf", "#697079"),
    Tier.BRONZE: ("#e8a262", "#9c5a23"),
    Tier.SILVER: ("#e2e7ed", "#8a93a0"),
    Tier.GOLD: ("#f6d365", "#cca017"),
    Tier.PLATINUM: ("#6fe3d2", "#2a9c99"),
    Tier.DIAMOND: ("#8cccff", "#2f7fe0"),
    Tier.MASTER: ("#c4a0ff", "#7d4fdb"),
    Tier.MARU: ("#ff9ad0", "#e0479b"),
}

# Medal tints for the strength trophies, ranked best -> third.
RANK_TINTS: list[tuple[str, str]] = [
    ("#f6d365", "#c79a17"),  # 1st — gold
    ("#d7dde5", "#9aa3b0"),  # 2nd — silver
    ("#e0a064", "#a86a2c"),  # 3rd — bronze
]


def hex_to_rgba(hex_color: str, alpha: float) -> str:
    """Convert a #rrggbb (or #rgb) color to an rgba() string with the given alpha."""
    h = hex_color.lstrip("#")
    if len(h) == 3:
        h = "".join(ch * 2 for ch in h)
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"rgba({r},{g},{b},{alpha})"
