# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.3.0] - 2026-09-03

### Fixed

- **Opening a card URL directly no longer drops the tier nameplate.** The card
  SVG's `default-src 'none'` CSP had no `img-src`, so the nameplate — an embedded
  base64 PNG — was blocked whenever the SVG was loaded straight in a browser tab.
  The policy now allows `img-src data:`, mirroring GitHub Camo's own SVG policy.
- **A degraded card recovers in a minute instead of a day.** A stale-fallback
  copy kept the full `CACHE_TTL_SECONDS` in the app cache (its restored
  `overallStatus` is `ok`, so only the `stale` flag gives it away), and every
  card — degraded or not — was sent `s-maxage=3600, stale-while-revalidate=86400`
  at the CDN, so an outage stayed pinned at the edge long after the platform came
  back. Stale and partial summaries now get the short negative TTL plus
  `max-age=60` and `s-maxage=60, stale-while-revalidate=300`.
- **A failed GitHub repository page no longer wipes out the whole profile.** A
  timeout or network error on page 2+ discarded the already-fetched first page,
  degrading GitHub to `unavailable` — a Seed card for an active account. The
  failure now keeps page 1 (followers, contributions, top repos) and degrades to
  `partial` with a note. Follow-up pages also get a tighter timeout — the lesser of
  3s (`MAX_FOLLOWUP_PAGE_TIMEOUT`) and what is left of the build deadline, and none is
  started with under a second to go — since their repos-only query is light.
- **GitHub API failures are no longer cached as "user not found".** A non-200
  first GraphQL page — an expired token (401), a rate limit (403) or a GitHub
  outage (5xx) — was noted `user not found`, and that note carries the
  10-minute `NOT_FOUND_CACHE_TTL_SECONDS`, so one outage pinned every handle
  requested during it as a missing user. Such failures are now noted
  `http <status>` and keep the 60s negative TTL; only a real "no such user"
  (HTTP 200 with `data.user: null`) earns the long TTL.
- **Generator: an animation toggle.** The API (`animate=false`), the CLI
  (`--no-animate`) and the Action (`animate: false`) all supported it, but the
  generator page had no control for it; it now has one, wired to the preview, the
  URL and every snippet.
- **The error card honours `compact`.** It always rendered at 640×300, so a
  compact embed — which reserves 250×270 — blew out the README layout whenever
  anything failed.
- **`/api/card.svg` never returns a 500.** Any unexpected exception (an adapter
  bug, the KV client, a renderer edge case) surfaced as a FastAPI 500, which is a
  broken image in someone's README. It now returns the visible error card
  (HTTP 200, `no-store`) and logs the traceback as a `card_error` event, so the
  branch can't swallow real bugs silently.
- **`/docs` and `/redoc` render again.** The generator page's `script-src 'self'`
  CSP applied to them too, and Swagger UI / ReDoc load their bundles from
  jsDelivr, so both pages came up blank. Those paths now get a docs-only policy
  that allows jsDelivr, Google Fonts (ReDoc pulls its text fonts from there) and
  inline scripts, which FastAPI's Swagger UI page needs to boot and offers no
  nonce hook for. The generator page and the card endpoints keep the strict policy.
- **Restored `sync-requirements.yml` and CI's Dependabot skip guard**, both
  deleted by accident. Dependabot's `uv` PRs bump `pyproject.toml` / `uv.lock`
  but can't regenerate the derived `requirements.txt`, so every one of them
  failed the drift check.
- **GitHub GraphQL errors are no longer cached as "user not found".** An HTTP 200
  with a top-level `errors` array (rate limiting, authorization failures) and no
  `data.user` now gets the short negative TTL; only a `NOT_FOUND` error keeps the
  long not-found TTL.
- **JungOl: a missing or malformed solved history marks the snapshot `partial`**
  instead of an `ok` snapshot with zero solves that could be cached for the full
  TTL and overwrite the last-good copy.

### Changed

- **Card text is outlined from pre-instanced static fonts.** Instancing a
  variable font costs ~200 ms per (family, weight) and a card needs five of them,
  so a cold serverless start spent about a second inside fontTools before drawing
  a single glyph. The instances are now built at development time and shipped in
  the package (`codemaru/render/assets/fonts/<Family>-<weight>.ttf`, regenerated
  with `uv run python scripts/instance_fonts.py`): a first render on a fresh
  process drops from ~940 ms to ~25 ms. Saving a TTF rounds outline coordinates
  to integers (`glyf` stores int16) — at most half a font unit, invisible at card
  scale — and the shorter path data makes cards ~27% smaller. A weight nobody
  pre-instanced still falls back to instancing at request time, so the variable
  fonts stay shipped.
- **The `<picture>` snippet follows the reader's GitHub theme.** It now pairs a
  `(prefers-color-scheme: dark)` `<source>` (`theme=dark`) with the selected
  theme on the `<img>` fallback. Picking `dark` in the generator makes the `<img>`
  fall back to `default`, so the pair really is light/dark; `transparent` stays
  as chosen, since it suits either scheme.
- **Generator polish.** The handle inputs carry mobile keyboard attributes
  (`inputmode`, autocapitalize / autocorrect / spellcheck off), the address bar is
  kept in sync with the form via `history.replaceState` so a reload or a shared
  link reproduces what's on screen, and the logo asset went from 265 KB to 22 KB.
- **`InMemoryCache` is bounded** at 1024 entries. A serverless instance can be
  reused for hours and the cache is keyed by profile, so an unbounded dict grew
  with every distinct handle ever requested on it. Eviction drops everything
  already expired first, then the oldest writes (FIFO, no per-read bookkeeping).
- **`/api/health` reports the deploy facts needed to diagnose a bad
  environment**: `version`, whether `kv` and `githubToken` are configured (never
  their values), and `cacheEntries`. `?deep=true` adds a KV `PING` round-trip as
  `kvPing` — opt-in, so a KV outage doesn't page anyone while cards render fine
  without it.
- **A GitHub handle that doesn't exist is cached for
  `NOT_FOUND_CACHE_TTL_SECONDS`** (default 600) instead of 60s: it isn't a
  transient failure, and re-asking the GraphQL API every minute only burns quota.
- **Judge platforms are a registry.** One row per judge in
  `codemaru/adapters/registry.py` carries its snapshot key, query param, label,
  confidence trust / saturation / weight and whether it shares the httpx client;
  scoring, confidence, the summary builder, the service, the query parser, the
  snippets and the CLI iterate it instead of naming judges, so adding one is a
  row plus an adapter. Tier bands shared by judges on the solved.ac scale moved
  to `adapters/tiers.py`, and snapshots expose a common `JudgeView`. Confidence
  weights stay additive and are never renormalized — sharing a fixed budget would
  lower existing users' cards whenever a judge is added. The refactor changes no
  score by itself; `SCORE_VERSION` moves to `0.4.0` with the JungOl entry below.
- **A whole-card build budget (`CARD_BUILD_TIMEOUT_SECONDS`, default 6s).**
  `ADAPTER_TIMEOUT_SECONDS` bounds one *request*, but GitHub paginates
  sequentially, so the worst case ran well past a serverless function's limit —
  and a function killed by the platform returns no error card and writes no
  negative cache entry. The fetch phase now runs under one ceiling: the platforms
  that finished are kept, the rest are cancelled and marked `unavailable` with a
  "timed out (card build budget)" note (the card renders as `partial`), and
  GitHub stops requesting repository pages cooperatively before the deadline
  instead of losing the pages it already paid for. The budget covers the fetch
  phase only, so it is sized against the KV calls bracketing it —
  `KV_TIMEOUT_SECONDS + CARD_BUILD_TIMEOUT_SECONDS + 2 * KV_TIMEOUT_SECONDS`, 9s
  at the defaults — which has to stay under the function timeout.
- **Structured JSON logging on stdout** (`codemaru/telemetry.py`): one line per
  `adapter`, `build`, `cache`, `kv_error` and `card_error` event, so "this card is
  slow" becomes a query over `event` / `platform` / `ms` instead of a guess. Only
  public handles are logged, and a caught exception contributes its class name
  rather than its message, which can carry a credentialed KV URL. The one
  deliberate exception is the card route's catch-all, which logs a full traceback
  because nothing else would ever surface that bug. `configure_logging()`
  always sets the `codemaru` logger to `INFO`, even on a host that already
  configured root logging (uvicorn, pytest, Vercel's runtime) — only the
  stdout handler is conditional on that.
- **The GitHub Action installs with `uv`** (`astral-sh/setup-uv`) instead of
  `pip`; the install step runs on every card refresh in every consumer's repo.
- **Removed dead code**: `LIVE_ADAPTERS_AVAILABLE`, `LiveDataUnavailableError`,
  the unused `REDIS_URL` setting, `render/fonts.py` and `DEFAULT_RENDER_OPTIONS`.

### Added

- **JungOl (정올) as a third judge.** Pass `jungol=<handle>` to `/api/card.svg` and
  `/api/summary.json`, `--jungol` to the CLI, or `jungol:` to the Action; the
  generator has a matching field. The adapter reads the `__data.json` that
  JungOl's own SvelteKit pages already serve — two GETs, no login, no HTML
  parsing and no new dependency — and decodes its devalue-flattened payload with
  a small pure function tested against saved live payloads. Any failure (HTTP
  error, timeout, schema drift, an oversized body) degrades to `unavailable`
  like every other adapter.

  JungOl uses the same 0–30 tier scale as solved.ac, so difficulty bands and tier
  names carry over; its rating signal is scaled by 0.80 because its problem pool
  is much smaller. The card shows **one** tier row, never two: `BOJ Tier` when
  solved.ac has data, `JungOl Tier` otherwise. Solved counts fold into the
  existing combined `Solved` metric.

  Additive throughout — solved counts are summed, rating evidence is a max, and
  the confidence weight (trust 0.60, saturation 900, weight 0.10) is added rather
  than carved out of the other judges' — so linking JungOl can never lower an
  existing card, and `snapshots.jungol` / `input.jungol` are new keys on a wire
  format that is otherwise unchanged. `SCORE_VERSION` moves to `0.4.0`, which
  expires every cache entry once (the new handle segment in the cache key does
  that anyway).

- **Documented why Programmers, CodeTree and SWEA are not collected**
  (`docs/SCORING.md`): none exposes a public profile or API without logging in,
  and codemaru will not ask anyone for platform credentials.

- **Two new workflows.** `major-tag.yml` force-moves the floating `v1` tag onto
  every published release, so `uses: bnbong/codemaru@v1` — what the README and
  the generator tell people to write — actually resolves; only plain `vX.Y.Z`
  releases move it, and the initial `v1` has to be created once by hand (see
  CONTRIBUTING). `action-smoke.yml` runs the composite action straight from the
  checkout on every PR that touches it, so a broken `action.yml` surfaces here
  instead of in a consumer's repo after a release.
- **Golden-digest render tests.** A render is byte-deterministic, so a SHA-256
  per demo variant pins layout, palette, animation CSS and font loading; after an
  intentional visual change, eyeball the SVG and refresh the digests with
  `uv run python -m tests.render.golden --update`. The suite also fails when the
  shipped static font instances drift from a fresh build
  (`scripts/instance_fonts.py --check`).

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

[1.3.0]: https://github.com/bnbong/codemaru/compare/v1.2.1...v1.3.0
[1.2.1]: https://github.com/bnbong/codemaru/compare/v1.2.0...v1.2.1
[1.2.0]: https://github.com/bnbong/codemaru/compare/v1.1.1...v1.2.0
[1.1.1]: https://github.com/bnbong/codemaru/compare/v1.1.0...v1.1.1
[1.1.0]: https://github.com/bnbong/codemaru/compare/v1.0.1...v1.1.0
[1.0.1]: https://github.com/bnbong/codemaru/compare/v1.0.0...v1.0.1
[1.0.0]: https://github.com/bnbong/codemaru/releases/tag/v1.0.0
