"""Validated request input. All external handles are constrained here so unsafe
values never reach scoring or the SVG output."""

from __future__ import annotations

import re

from pydantic import BaseModel, field_validator

# Real GitHub rule: alphanumeric with single internal hyphens, max 39 chars.
GITHUB_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?$")
# Judge handles (solved.ac/BOJ, LeetCode) also allow underscores and dots.
PLATFORM_RE = re.compile(r"^[A-Za-z0-9._-]{1,39}$")


class ProfileInput(BaseModel):
    """The set of platform handles a card is built from."""

    github: str
    boj: str | None = None
    leetcode: str | None = None

    @field_validator("github")
    @classmethod
    def _validate_github(cls, value: str) -> str:
        v = value.strip()
        if not GITHUB_RE.match(v):
            raise ValueError("invalid GitHub username (letters, numbers and single hyphens only)")
        return v

    @field_validator("boj", "leetcode", mode="before")
    @classmethod
    def _empty_to_none(cls, value: str | None) -> str | None:
        if value is None:
            return None
        v = value.strip()
        return v or None

    @field_validator("boj", "leetcode")
    @classmethod
    def _validate_platform(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not PLATFORM_RE.match(value):
            raise ValueError("invalid handle (letters, numbers, . _ - only)")
        return value
