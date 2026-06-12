# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.2.1] - 2026-06-12

### Changed

- **Summary cache is shared across instances via Vercel KV (Upstash Redis).**
  When `KV_REST_API_URL` / `KV_REST_API_TOKEN` are set, computed summaries and the
  stale-fallback store live in Redis instead of per-instance memory, so a cold
  serverless instance reuses a warm cache and skips the live fetch — cutting the
  first-view "broken image until refresh" timeout. Best-effort: missing creds
  (local / CI) or any KV error transparently falls back to the in-memory cache and
  never affects rendering — and every KV write is mirrored locally, so a transient
  KV read outage *or* a remote miss (e.g. a dropped write / eviction) still serves
  a warm instance from the mirror instead of rebuilding every request.
  Reuses the same KV store as adoption tracking (disjoint
  key namespaces). Cache keys are scoped by deploy env (`VERCEL_ENV`) and mode
  (fixture/live) so a preview deploy or fixture data can't pollute production, and
  a cached payload that fails to deserialize (e.g. written by a different deploy's
  schema) is treated as a miss and rebuilt rather than surfacing a 500.
- **Measured impact.** Local CPU work is not the bottleneck (`build_summary` is
  about 0.05 ms, `render_card` about 0.77 ms, and cache JSON parse/store stays
  below 0.02 ms); the expensive path is live platform fetches. In observed live
  requests, GitHub-dominated fetches took roughly 2.0-5.5 s, while a warm shared
  KV hit only needs a small JSON payload read plus parsing (typically tens of ms
  or less in-region). This mainly helps cold/new serverless instances serving an
  already-cached profile; CDN hits remain edge-fast, and a truly first-time cache
  miss still has to perform the live fetch.

## [1.2.0] - 2026-06-11

### Added

- **Animated tier emblem.** Cards now play a one-shot entrance animation: the
  hex crest stamps in, then the score, the wing-rest and the wings swinging in
  from each side, the crown spikes rising left-to-right, the apex gem dropping
  in, and the nameplate wiping in. It's pure CSS `@keyframes`
  embedded in the SVG, so it runs even when the card is an `<img>` in a README
  (no scripts). Nothing is hidden by base styles, so any renderer that ignores
  the stylesheet — or a viewer with `prefers-reduced-motion` — still gets the
  full static card. Opt out with `?animate=false` (API), `--no-animate` (CLI), or
  the Action's `animate: false` input.
- **Generator preview: replay + loading spinner.** The preview now shows a
  spinner while a card (re)loads, and a **Replay** button re-runs the entrance
  animation without changing inputs.

## [1.1.1] - 2026-06-11

### Security

- **Adoption tracking can no longer be spoofed or used to exhaust KV quota.**
  Card embeds are now recorded only when the request is from Camo *and* the
  GitHub snapshot is real (not `unavailable`), so a forged `User-Agent: camo`
  against non-existent handles can't inflate the badge. The distinct-user store
  moved from a Redis SET to a **HyperLogLog** (`PFADD`/`PFCOUNT`): a fixed ~12KB
  ceiling regardless of cardinality, so a flood can't grow storage without bound.
  (The badge count restarts from 0 on a new key — expected for a HLL switch.)
- **Cloudflare-proxy bypass guard.** An optional `ORIGIN_SHARED_SECRET` makes the
  app reject any request that lacks a matching `X-Origin-Auth` header (injected by
  a Cloudflare request-header Transform Rule), so direct hits on the raw
  `*.vercel.app` origin — which skip the WAF / rate limits — are blocked. Unlike a
  Host-name check it can't be bypassed by spoofing Host. Disabled by default; set
  only in production with the Cloudflare rule deployed first.
- **Security response headers.** All responses send `X-Content-Type-Options:
  nosniff`; the generator page adds a `Content-Security-Policy`, `X-Frame-Options:
  DENY`, and `Referrer-Policy`; card SVGs send a locked-down `default-src 'none'`
  CSP (defense-in-depth for direct opens).
- **Supply chain hardening.** `requirements.txt` is now fully pinned from
  `uv.lock` (no more `>=` ranges that let Vercel install untested versions), with
  a CI check that fails if it drifts from the lockfile. All GitHub Actions are
  pinned to commit SHAs, and Dependabot keeps both Actions and Python deps
  updated.

## [1.1.0] - 2026-06-10

### Changed

- **Scoring overhaul (`SCORE_VERSION` → `0.3.0`).** A batch of fairness fixes to
  how profiles are ranked:
  - *Confidence* now scales with each platform's **verifiable solve volume**
    (weighted by source trust), not mere account presence — so linking a
    brand-new judge account with a handful of solves no longer bumps the tier.
    GitHub confidence also credits a standout owned project, so a historically
    significant flagship isn't capped low just for being recently quiet.
  - *Tier caps* gained a distinct **Master** step and were re-tuned: a strong
    **single-source** profile (e.g. GitHub-only) can now reach up to **Master**,
    while the top tier **Maru** is reserved for an all-round, multi-platform
    *pentagon* (deep across both open-source and algorithm activity).
  - *Open Source* weights commits and contributed repos most (0.40 / 0.20) and
    leans less on PRs/reviews/issues, so a prolific direct-commit maintainer who
    rarely opens PRs isn't scored into the ground.
  - *Depth* is redesigned into three pillars — algorithmic depth (judges), a
    **representative-project** signal (the most-starred *owned* repo, a new
    snapshot field), and technical breadth — combined so deep algorithms **or**
    one significant built project can carry it (breadth only fills ≤15% of the
    headroom). Org-owned flagships (e.g. `python/cpython`) aren't attributed —
    a known public-data limitation.
- **Card metrics: LeetCode folded into a combined "Solved".** The standalone
  LeetCode metric is removed; "Solved" is now the total problems solved across
  all judges (BOJ + LeetCode, and future platforms). LeetCode still feeds the
  scores. The Solved metric shows even for a LeetCode-only profile.

### Added

- **Adoption tracking + README badge.** A new `GET /api/stats/badge` shields.io
  endpoint reports how many distinct developers have embedded a codemaru card.
  Card requests coming from GitHub's image proxy (Camo) — real README embeds —
  record the handle in a Vercel KV (Upstash Redis) set; the badge shows the
  `SCARD`. Best-effort: without `KV_REST_API_URL` / `KV_REST_API_TOKEN` (local /
  CI) tracking is a no-op and a failing KV never affects card rendering. Only the
  public, lower-cased handle is stored — no viewer IPs/headers.

### Fixed

- **High-activity GitHub profiles no longer drop to "unavailable".** The live
  adapter's per-request read timeout (3s) was too tight for accounts whose
  GraphQL query is heavy (many repos plus a year of contributions): the first
  page alone could take 3–4s, time out, and degrade the whole card to a
  GitHub-less `partial`. The read budget is raised to 8s (connect stays short so
  a dead host still fails fast), and follow-up repository pages now use a
  lighter repos-only query that doesn't re-fetch the expensive contribution
  aggregation — bounding multi-page cost so it stays within the serverless limit.

## [1.0.1] - 2026-06-09

### Changed

- **Cross-platform scoring is now monotonic** (`scoreVersion` 0.2.0) — linking
  another algorithm judge can no longer lower your tier. Problem Solving now
  **sums** solved counts across judges (saturated once) instead of averaging
  per-platform scores, and Depth takes the **best** rating (BOJ tier vs LeetCode
  contest) with **summed** hard-problem volume, counting only platforms that
  contribute positive evidence. A freshly created account no longer dilutes an
  established profile.
- **Tier crest crown** redesigned so the spike count reads as a rank: 3 at Gold,
  +1 per tier up to 7 at Maru (no spikes below Gold).
- **Card text is rendered as vector outlines** using bundled Space Grotesk /
  JetBrains Mono (both OFL). GitHub renders README SVGs with web fonts disabled,
  so text previously fell back to system fonts (inconsistent across macOS /
  Windows); outlining bakes the designed fonts into the geometry so the card
  looks identical everywhere. Repeated glyphs are de-duplicated via `<defs>`/
  `<use>` to keep the SVG small.

### Fixed

- **Compact layout** no longer overlaps the `@handle` and the `codemaru`
  wordmark (compact height 256 → 270).
- **Handle underline** now matches the handle width exactly — fixed a
  scale-rounding bug that mis-sized all outlined text and left a long trailing
  underline.
- **Version is single-sourced** from `__version__`: the FastAPI app version and
  the adapter `User-Agent` no longer carry a hard-coded `0.1`.

### Docs

- Bilingual README (English / 한국어) with a language switcher; the API
  reference and fixture/live-mode notes moved to `CONTRIBUTING.md`; added
  theme, compact, and generator preview images.

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

[1.2.1]: https://github.com/bnbong/codemaru/compare/v1.2.0...v1.2.1
[1.2.0]: https://github.com/bnbong/codemaru/compare/v1.2.0
[1.1.1]: https://github.com/bnbong/codemaru/compare/v1.1.1
[1.1.0]: https://github.com/bnbong/codemaru/compare/v1.1.0
[1.0.1]: https://github.com/bnbong/codemaru/compare/v1.0.1
[1.0.0]: https://github.com/bnbong/codemaru/releases/tag/v1.0.0
