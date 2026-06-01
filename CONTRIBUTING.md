# Contributing to codemaru

codemaru is a Python 3.12+ / FastAPI service. It renders developer
programming-activity summary cards as self-contained SVG for GitHub READMEs.

## Setup

```bash
uv sync
uv run uvicorn codemaru.app:app --reload   # http://localhost:8000
```

## Project layout

```
codemaru/
  app.py            # FastAPI app + ASGI `app`
  settings.py       # Pydantic settings
  service.py        # input → (cache | adapters) → scoring → summary
  models/           # Pydantic domain models
  core/             # normalization, scoring, confidence, tier, strengths, summary
  render/           # pure-SVG renderer (xml, themes, radar, icons, card)
  web/              # query parsing, embed snippets, routes
  cache/            # Cache protocol + in-memory backend
  fixtures/         # deterministic demo data
templates/ static/  # server-rendered generator UI
api/index.py        # Vercel entrypoint
tests/              # core, models, render, api, web
```

Keep the boundaries clean: **adapters** fetch data, **core** scores it,
**render** builds SVG strings, **web/api** validates input and coordinates.
Don't put scoring formulas or SVG layout math in route handlers.

## Checks (must pass before opening a PR)

```bash
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run mypy codemaru
```

Live external API calls are excluded from default CI; mark such tests with
`@pytest.mark.integration`.

## Conventions

- The card SVG must render in GitHub README Markdown: no JavaScript, no external
  images, no animation. Escape all user-provided text (`render/xml.py`).
- The radar always has exactly five axes; there is no axis-hide option.
- Confidence is never drawn on the card, but stays in `summary.json` and caps
  the tier.
- When you change any scoring formula, bump `SCORE_VERSION` and update tests.
- Ask for review when changing scoring, adapters, caching, deployment, or SVG
  layout.

## Pull requests

Keep PRs small and reviewable. The current rewrite PR is fixture-mode only; real
GitHub / solved.ac / LeetCode adapters come in a follow-up behind the existing
`service.py` cache boundary.
