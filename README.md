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

A Python / FastAPI service that turns your public developer activity into an embeddable SVG card.

## Quick start

```bash
uv sync                          # install deps into .venv
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

> **Fixture mode only (for now).** Live adapters aren't implemented yet, so
> `FIXTURE_MODE` defaults to `true` and `/api/health` reports `"mode":
> "fixture"`. Setting `FIXTURE_MODE=false` is treated as a configuration error
> (card → error card, JSON → 503, health → `"unavailable"`) rather than serving
> fixture data dressed up as live.

## Scoring (v0, `SCORE_VERSION = 0.1.0`)

Scores summarize **public activity** — not an absolute skill rating. 

All scoring functions are pure; raw counts are never summed directly — unbounded counts use logarithmic saturation (`log1p(value)/log1p(saturation)`).

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

Tiers: `Seed → Bronze → Silver → Gold → Platinum → Diamond → Master → Maru`