# Contributing to codemaru

Thanks for helping out! codemaru is a Python 3.12+ / FastAPI service that renders
developer activity into an embeddable SVG card.

## Setup

```bash
uv sync                                    # install deps into .venv
uv run uvicorn codemaru.app:app --reload   # http://localhost:8000
```

## API

```
GET /                  # server-rendered generator (live preview + copy snippets)
GET /api/card.svg      # image/svg+xml
GET /api/summary.json  # application/json
GET /api/health        # liveness + scoreVersion
```

Query params: `github` (required), `boj`, `leetcode`, `theme` (`default`|`dark`|`transparent`), `compact` (`true`/`false`).

- Invalid input returns a **visible SVG error card with HTTP 200** (plus an
  `X-Codemaru-Error: true` header and `Cache-Control: no-store`) so GitHub's
  image proxy renders the error instead of a broken image; `summary.json`
  returns a structured `{ "error": ... }` with a 4xx/5xx status.
- Cards send `Cache-Control: public, max-age=300` plus
  `CDN-Cache-Control` / `Vercel-CDN-Cache-Control` `s-maxage=3600,
  stale-while-revalidate=86400`, and an `ETag`.

## Fixture mode vs live mode

`FIXTURE_MODE` defaults to **`true`** so local dev and CI need no secrets or network — endpoints serve deterministic fixtures and `/api/health` reports `"mode": "fixture"`.

Set `FIXTURE_MODE=false` for **live mode**: GitHub, solved.ac, and LeetCode are fetched concurrently with a per-request timeout (`ADAPTER_TIMEOUT_SECONDS`).

Live GitHub data requires `GITHUB_TOKEN` (the GraphQL API needs auth); without it the GitHub snapshot is `unavailable`.

Each adapter maps any failure (HTTP error, timeout, schema drift, blocked request) to an `unavailable` snapshot, so one platform failing degrades the card to `partial` instead of breaking it.

> **Note:** solved.ac sits behind Cloudflare, which rejects plain-Python TLS
> fingerprints (a 403 "Just a moment…" challenge). codemaru fetches it with a
> browser-impersonating TLS client (`curl_cffi`, Chrome profile); if it's ever
> still blocked, the BOJ axis degrades to unavailable. LeetCode's endpoint is
> unofficial and treated as experimental.

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
  escape all user-provided text (`codemaru/render/xml.py`).
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
