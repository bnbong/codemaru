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


def test_generate_reports_a_runtime_failure_as_exit_1(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    # A workflow wants an exit code, not a traceback. 1 (runtime failure) stays
    # distinct from 2 (bad arguments).
    out = tmp_path / "codemaru.svg"

    async def boom(profile: ProfileInput) -> CodemaruSummary:
        raise RuntimeError("everything is on fire")

    monkeypatch.setattr("codemaru.service.get_summary", boom)

    rc = cli.main(["generate", "--github", "octocat", "--out", str(out)])

    assert rc == 1
    assert not out.exists()
    assert "everything is on fire" in capsys.readouterr().err


def test_generate_accepts_a_jungol_handle(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    # The flag is generated from the registry, so this also proves a new judge
    # reaches the Action (which shells out to exactly this CLI).
    seen: list[ProfileInput] = []

    async def fake_get_summary(profile: ProfileInput) -> CodemaruSummary:
        seen.append(profile)
        return _fake_summary(profile)

    monkeypatch.setattr("codemaru.service.get_summary", fake_get_summary)
    out = tmp_path / "codemaru.svg"

    rc = cli.main(["generate", "--github", "octocat", "--jungol", "jo", "--out", str(out)])

    assert rc == 0
    assert seen[0].jungol == "jo"
    assert out.exists()


def test_generate_rejects_an_invalid_jungol_handle(tmp_path: Path):
    out = tmp_path / "codemaru.svg"
    rc = cli.main(["generate", "--github", "octocat", "--jungol", "bad handle", "--out", str(out)])
    assert rc == 2
    assert not out.exists()


def test_every_judge_has_a_cli_flag():
    from codemaru.adapters.registry import JUDGES

    help_text = cli._build_parser().parse_args(["generate", "--github", "x", "--out", "y"])
    for platform in JUDGES:
        assert hasattr(help_text, platform.param)
