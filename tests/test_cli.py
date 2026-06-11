"""Tests for the `codemaru generate` CLI used by the GitHub Action."""

from __future__ import annotations

from pathlib import Path

import pytest

from codemaru import cli
from codemaru.core.summary import build_summary
from codemaru.fixtures.demo import FIXED_TIMESTAMP, resolve_fixture_bundle
from codemaru.models.input import ProfileInput
from codemaru.models.summary import CodemaruSummary


def _fake_summary(profile: ProfileInput) -> CodemaruSummary:
    return build_summary(profile, resolve_fixture_bundle(profile), FIXED_TIMESTAMP)


def test_generate_writes_svg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    out = tmp_path / "nested" / "codemaru.svg"

    async def fake_get_summary(profile: ProfileInput) -> CodemaruSummary:
        return _fake_summary(profile)

    # The CLI imports get_summary from the service module at call time.
    monkeypatch.setattr("codemaru.service.get_summary", fake_get_summary)

    rc = cli.main(["generate", "--github", "octocat", "--boj", "octo", "--out", str(out)])

    assert rc == 0
    assert out.exists()  # parent directory is created automatically
    assert "<svg" in out.read_text(encoding="utf-8")


def test_generate_animation_default_and_opt_out(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    async def fake_get_summary(profile: ProfileInput) -> CodemaruSummary:
        return _fake_summary(profile)

    monkeypatch.setattr("codemaru.service.get_summary", fake_get_summary)

    animated = tmp_path / "anim.svg"
    assert cli.main(["generate", "--github", "octocat", "--out", str(animated)]) == 0
    assert "<style>" in animated.read_text(encoding="utf-8")  # animation on by default

    static = tmp_path / "static.svg"
    assert cli.main(["generate", "--github", "octocat", "--no-animate", "--out", str(static)]) == 0
    assert "<style>" not in static.read_text(encoding="utf-8")  # --no-animate is static


def test_generate_rejects_invalid_username(tmp_path: Path):
    out = tmp_path / "codemaru.svg"
    rc = cli.main(["generate", "--github", "bad_name", "--out", str(out)])
    assert rc == 2
    assert not out.exists()
