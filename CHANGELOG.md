# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0] - 2026-06-05

First public release. codemaru turns a developer's public activity into a
self-contained, embeddable SVG summary card for GitHub profile READMEs.

### Added

- **Summary card** — a pure-SVG, self-contained card (no JS, no external
  resources) embeddable in any GitHub README. Faceted hexagonal emblem with a
  마루 crest ornament, calligraphy tier nameplate, top-3 strength medal badges,
  a fixed 5-axis radar, and a supporting-metric row.
- **Tier ladder** — eight ranks from Seed to Maru
  (Seed → Bronze → Silver → Gold → Platinum → Diamond → Master → Maru).
- **Themes & layouts** — `default`, `dark`, and `transparent` themes, plus a
  `compact` (tier-panel-only) layout.
- **Scoring** — five axes (Open Source, Impact, Consistency, Problem Solving,
  Depth) combined into an overall score with logarithmic saturation;
  confidence is weighted across platforms and caps the tier. Pure, versioned
  scoring functions (`SCORE_VERSION`).
- **Data adapters** — GitHub (paginated GraphQL), solved.ac (via a
  browser-impersonating TLS client to pass Cloudflare), and LeetCode
  (unofficial GraphQL). Any platform failure degrades the card to `partial`
  instead of breaking it, with status-aware caching and a last-good stale
  fallback during outages.
- **Hosted generator** — a web UI at
  [codemaru.bnbong.com](https://codemaru.bnbong.com) with a live preview and
  copy-paste Markdown / HTML `<picture>` / GitHub Action snippets.
- **HTTP API** — `GET /api/card.svg`, `GET /api/summary.json`, and
  `GET /api/health`. Invalid input returns a visible SVG error card with HTTP
  200 (so image proxies render it, not a broken image); cards send CDN cache
  headers and an `ETag`.
- **GitHub Action** — `bnbong/codemaru`, a composite action that runs the same
  scoring/render pipeline in your own repo's CI and commits a static SVG, so
  the card loads straight from your repository with no dependency on the hosted
  endpoint.
- **CLI** — `codemaru generate --github <user> --out <path>` for local/static
  card generation (the engine behind the Action).
- **Deployment** — runs on Vercel as a FastAPI ASGI app.
- **Docs & project hygiene** — bilingual README (English / 한국어),
  CONTRIBUTING guide, issue/PR templates, CI (ruff, mypy, pytest + coverage),
  release-drafter, and PR labeler.

[1.0.0]: https://github.com/bnbong/codemaru/releases/tag/v1.0.0
