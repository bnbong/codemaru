[English](#contributing-to-codemaru) · [한국어](#codemaru에-기여하기)

# Contributing to codemaru

Thanks for helping out! codemaru is a Python 3.12+ / FastAPI service that renders developer activity into an embeddable SVG card.

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
GET /api/stats/badge   # shields.io endpoint badge: distinct embedded users
```

Query params: `github` (required), `boj`, `leetcode`, `theme` (`default`|`dark`|`transparent`), `compact` (`true`/`false`), `animate` (`true`/`false`, default `true` — the one-shot entrance animation; `animate=false` ships a static card).

- Invalid input returns a **visible SVG error card with HTTP 200** (plus an `X-Codemaru-Error: true` header and `Cache-Control: no-store`) so GitHub's image proxy renders the error instead of a broken image; `summary.json` returns a structured `{ "error": ... }` with a 4xx/5xx status.
- Cards send `Cache-Control: public, max-age=300` plus `CDN-Cache-Control` / `Vercel-CDN-Cache-Control` `s-maxage=3600, stale-while-revalidate=86400`, and an `ETag`.

## Fixture mode vs live mode

`FIXTURE_MODE` defaults to **`true`** so local dev and CI need no secrets or network — endpoints serve deterministic fixtures and `/api/health` reports `"mode": "fixture"`.

Set `FIXTURE_MODE=false` for **live mode**: GitHub, solved.ac, and LeetCode are fetched concurrently with a per-request timeout (`ADAPTER_TIMEOUT_SECONDS`).

Live GitHub data requires `GITHUB_TOKEN` (the GraphQL API needs auth); without it the GitHub snapshot is `unavailable`.

Each adapter maps any failure (HTTP error, timeout, schema drift, blocked request) to an `unavailable` snapshot, so one platform failing degrades the card to `partial` instead of breaking it.

A computed summary is cached (`CACHE_TTL_SECONDS`); when Vercel KV (`KV_REST_API_URL` / `KV_REST_API_TOKEN`) is configured the cache is shared across instances, otherwise it falls back to per-instance memory. Either way it's best-effort — a KV outage never affects rendering.

> **Note:** solved.ac sits behind Cloudflare, which rejects plain-Python TLS
> fingerprints (a 403 "Just a moment…" challenge). codemaru fetches it with a
> browser-impersonating TLS client (`curl_cffi`, Chrome profile); if it's ever
> still blocked, the BOJ axis degrades to unavailable. LeetCode's endpoint is
> unofficial and treated as experimental.

## Before you open a PR

CI runs these on every PR — run them locally first:

```bash
uv run pytest -m "not integration"
uv run ruff check .
uv run ruff format --check .   # `uv run ruff format .` to fix
uv run mypy codemaru
```

Live external-API tests are opt-in (`@pytest.mark.integration`) and excluded from CI; default tests use fixtures and need no network or secrets.

## A few conventions

- The card SVG must render in a GitHub README: no JS, no external resources; escape all user-provided text (`codemaru/render/xml.py`). The tier icon animation is CSS-only (`@keyframes`) and degrades to a full static card where the stylesheet is ignored or `prefers-reduced-motion` is set.
- The radar is always 5 axes; confidence is never drawn on the card (it lives in `summary.json` and caps the tier).
- Change any scoring formula → bump `SCORE_VERSION` and update the tests.
- Adoption tracking (`codemaru/analytics.py`) and the shared KV cache (`codemaru/kv.py`) are best-effort: they must never block or break card rendering, and are a no-op locally (no secrets needed to develop or test).
- Keep PRs small and focused.

---

[English](#contributing-to-codemaru) · [한국어](#codemaru에-기여하기)

# codemaru에 기여하기

도움 주셔서 감사합니다! codemaru는 개발자 활동을 GitHub README에 넣을 수 있는 SVG 카드로 렌더링하는 Python 3.12+ / FastAPI 서비스입니다.

## 설치

```bash
uv sync                                    # 의존성을 .venv에 설치
uv run uvicorn codemaru.app:app --reload   # http://localhost:8000
```

## API

```
GET /                  # 서버 렌더 생성기 (실시간 미리보기 + 스니펫 복사)
GET /api/card.svg      # image/svg+xml
GET /api/summary.json  # application/json
GET /api/health        # 헬스 체크 + scoreVersion
GET /api/stats/badge   # shields.io 엔드포인트 배지: 임베드한 distinct 사용자 수
```

쿼리 파라미터: `github` (필수), `boj`, `leetcode`, `theme` (`default`|`dark`|`transparent`), `compact` (`true`/`false`), `animate` (`true`/`false`, 기본 `true` — 1회성 등장 애니메이션; `animate=false`면 정적 카드).

- 잘못된 입력에는 **HTTP 200으로 보이는 SVG 에러 카드**를 반환합니다(`X-Codemaru-Error: true` 헤더와 `Cache-Control: no-store` 포함). GitHub 이미지 프록시가 깨진 이미지 대신 에러를 렌더링하도록 하기 위함입니다. `summary.json`은 4xx/5xx 상태와 함께 구조화된 `{ "error": ... }`를 반환합니다.
- 카드는 `Cache-Control: public, max-age=300`와 함께 `CDN-Cache-Control` / `Vercel-CDN-Cache-Control` `s-maxage=3600, stale-while-revalidate=86400`, 그리고 `ETag`를 보냅니다.

## Fixture 모드 vs Live 모드

`FIXTURE_MODE`는 기본값이 **`true`**라 로컬 개발과 CI에 시크릿이나 네트워크가 필요 없습니다. 엔드포인트는 결정적 fixture를 서빙하고 `/api/health`는 `"mode": "fixture"`를 보고합니다.

**Live 모드**는 `FIXTURE_MODE=false`로 켭니다. GitHub, solved.ac, LeetCode를 요청별 타임아웃(`ADAPTER_TIMEOUT_SECONDS`)으로 동시에 가져옵니다.

라이브 GitHub 데이터에는 `GITHUB_TOKEN`이 필요합니다(GraphQL API는 인증이 필수입니다). 토큰이 없으면 GitHub 스냅샷은 `unavailable`이 됩니다.

각 어댑터는 모든 실패(HTTP 오류, 타임아웃, 스키마 변경, 차단된 요청)를 `unavailable` 스냅샷으로 처리합니다. 그래서 한 플랫폼이 실패해도 카드가 깨지지 않고 `partial`로 degrade됩니다.

계산된 요약은 캐시됩니다(`CACHE_TTL_SECONDS`). Vercel KV(`KV_REST_API_URL` / `KV_REST_API_TOKEN`)가 설정돼 있으면 캐시를 인스턴스 간에 공유하고, 없으면 인스턴스 로컬 메모리로 폴백합니다. 어느 쪽이든 best-effort라 KV가 장애를 일으켜도 렌더링에는 영향이 없습니다.

> **참고:** solved.ac는 Cloudflare 뒤에 있어 순수 파이썬 TLS 지문을 거부합니다
> (403 "Just a moment…" 챌린지). codemaru는 브라우저를 모방하는 TLS 클라이언트
> (`curl_cffi`, Chrome 프로필)로 가져옵니다. 그래도 막히면 BOJ 축이 unavailable로
> degrade됩니다. LeetCode 엔드포인트는 비공식이라 실험적으로 취급합니다.

## PR을 열기 전에

CI가 매 PR마다 다음을 실행합니다 — 먼저 로컬에서 돌려보세요:

```bash
uv run pytest -m "not integration"
uv run ruff check .
uv run ruff format --check .   # 고치려면 `uv run ruff format .`
uv run mypy codemaru
```

라이브 외부 API 테스트는 옵트인(`@pytest.mark.integration`)이며 CI에서 제외됩니다. 기본 테스트는 fixture를 사용하므로 네트워크나 시크릿이 필요 없습니다.

## 몇 가지 컨벤션

- 카드 SVG는 GitHub README에서 렌더되어야 합니다. JS 금지, 외부 리소스 금지, 사용자 입력은 모두 이스케이프합니다(`codemaru/render/xml.py`). 티어 아이콘 애니메이션은 CSS 전용(`@keyframes`)이며, 스타일시트가 무시되거나 `prefers-reduced-motion`이 켜진 환경에서는 완전한 정적 카드로 degrade됩니다.
- 레이더는 항상 5축이며, confidence는 카드에 절대 그리지 않습니다(`summary.json`에만 두고 티어 상한으로만 씁니다).
- 점수 공식을 바꾸면 `SCORE_VERSION`을 올리고 테스트를 갱신하세요.
- 입양 추적(`codemaru/analytics.py`)과 공유 KV 캐시(`codemaru/kv.py`)는 best-effort입니다. 카드 렌더링을 막거나 깨뜨려선 안 되며, 로컬에서는 no-op으로 동작합니다(개발과 테스트에 시크릿이 필요 없습니다).
- PR은 작고 집중되게 유지하세요.
