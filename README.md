<p align="center">
  <img src=".github/codemaru_logo_text.png" alt="codemaru"/>
</p>
<p align="center">
<em><b>Codemaru:</b> Render a developer's public activity and algorithm-training stats as an embeddable <b>summary card</b> for GitHub profile READMEs. </em>
</p>
<p align="center">
<img src="https://img.shields.io/badge/Python-3.12+-3776ab.svg?style=flat&logo=python&logoColor=white" alt="Python"/>
<img src="https://img.shields.io/badge/FastAPI-009688.svg?style=flat&logo=fastapi&logoColor=white" alt="FastAPI"/>
<a href="https://codecov.io/gh/bnbong/codemaru" >
 <img src="https://codecov.io/gh/bnbong/codemaru/graph/badge.svg?token=A7B1BHUtSm"/>
 </a>
</p>

---

> `code` + 순우리말 `마루` — climb to the top of your coding ability and keep growing.

A tool that turns your public developer activity into an embeddable SVG card. 

It reads **GitHub**, **BOJ / solved.ac**, and **LeetCode**, scores it across five axes, places you on an 8-rung tier ladder, and renders a self-contained, themeable card you can drop into a README.

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset=".github/preview/card-dark.png">
    <img width="560" alt="codemaru summary card" src=".github/preview/card-light.png">
  </picture>
</p>

## The card

The left **tier panel** carries a faceted hexagonal **emblem** (the overall score sits in the medallion) wrapped in a 마루 crest ornament — a sun-ray summit crown with laurel fronds that grows richer with rank. 

Below it sits the tier's **calligraphy nameplate**, the **top-3 strengths** as competency-glyph medal badges (gold / silver / bronze by rank), and your `@handle`, linked to your GitHub profile. 

The right side is a fixed **5-axis radar** with a supporting **metric row**. Three themes (`default` / `dark` / `transparent`) and a **compact** layout (tier panel only, `250×256`) are available.

## Tiers

Eight ranks, from a humble Seed to the summit, **Maru**:

<p align="center">
  <img width="820" alt="codemaru tier ladder: Seed, Bronze, Silver, Gold, Platinum, Diamond, Master, Maru" src=".github/preview/tier-ladder.png">
</p>

```
Seed → Bronze → Silver → Gold → Platinum → Diamond → Master → Maru
```

## Quick start

```bash
uv sync                          # install deps into .venv
uv run uvicorn codemaru.app:app --reload   # http://localhost:8000
```

Open `http://localhost:8000` for the generator (live preview + copy snippets),
or call the API directly.

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

### Fixture mode vs live mode

`FIXTURE_MODE` defaults to **`true`** so local dev and CI need no secrets or network — endpoints serve deterministic fixtures and `/api/health` reports `"mode": "fixture"`.

Set `FIXTURE_MODE=false` for **live mode**: GitHub, solved.ac, and LeetCode are fetched concurrently with a per-request timeout (`ADAPTER_TIMEOUT_SECONDS`). 

Live GitHub data requires `GITHUB_TOKEN` (the GraphQL API needs auth); without it the GitHub snapshot is `unavailable`. 

Each adapter maps any failure (HTTP error, timeout, schema drift, blocked request) to an `unavailable` snapshot, so one platform failing degrades the card to `partial` instead of breaking it.

> **Note:** solved.ac sits behind Cloudflare, which rejects plain-Python TLS
> fingerprints (a 403 "Just a moment…" challenge). codemaru fetches it with a
> browser-impersonating TLS client (`curl_cffi`, Chrome profile); if it's ever
> still blocked, the BOJ axis degrades to unavailable. LeetCode's endpoint is
> unofficial and treated as experimental.

## Scoring

Scores summarize **public activity** — not an absolute skill rating. 

All scoring functions are pure; raw counts are never summed directly — unbounded counts use logarithmic saturation, $\dfrac{\ln(1 + \text{value})}{\ln(1 + \text{saturation})}$, where `saturation` is the count at which the score reaches ~100.

| Axis            | Signals (source)                                                |
| --------------- | --------------------------------------------------------------- |
| Open Source     | commits, PRs, reviews, contributed repos, issues (GitHub)       |
| Impact          | stars, forks, followers, public repos (GitHub)                  |
| Consistency     | active days, longest streak (GitHub)                            |
| Problem Solving | solved counts (solved.ac + LeetCode)                            |
| Depth           | BOJ tier, hard-problem mix, LeetCode hard/contest, lang breadth |

```
overall = 0.30*openSource + 0.20*problemSolving + 0.20*depth
        + 0.15*consistency + 0.15*impact
```

Confidence is weighted across platforms (GitHub ×0.6 volume-weighted, solved.ac ×0.25, LeetCode ×0.15 discounted as experimental); 

low confidence caps the tier so a GitHub-only profile tops out at Gold.