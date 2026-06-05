# Contributing to codemaru

Thanks for helping out! codemaru is a Python 3.12+ / FastAPI service that renders
developer activity into an embeddable SVG card.

## Setup

```bash
uv sync                                    # install deps into .venv
uv run uvicorn codemaru.app:app --reload   # http://localhost:8000
```

## Before you open a PR

CI runs these on every PR — run them locally first:

```bash
uv run pytest
uv run ruff check .
uv run ruff format --check .   # `uv run ruff format .` to fix
uv run mypy codemaru
```

Live external-API tests are opt-in (`@pytest.mark.integration`) and excluded
from CI; default tests use fixtures and need no network or secrets.

## A few conventions

- The card SVG must render in a GitHub README: no JS, no external resources;
  escape all user-provided text (`render/xml.py`).
- The radar is always 5 axes; confidence is never drawn on the card (it lives in
  `summary.json` and caps the tier).
- Change any scoring formula → bump `SCORE_VERSION` and update the tests.
- Keep PRs small and focused.

## PRs & labels

Use a Conventional-Commit-style title (`feat:`, `fix:`, `docs:`, `chore:`,
`ci:`, `test:`) — it auto-applies labels and feeds the drafted release notes.
Path-based labels (`area: render`, `area: adapters`, …) are added automatically.

For scoring, adapter, caching, deployment, or SVG-layout changes, please ask for
a review.
