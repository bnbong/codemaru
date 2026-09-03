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
GET /api/health        # liveness + version, config and cache state
GET /api/stats/badge   # shields.io endpoint badge: distinct embedded users
```

Query params: `github` (required), `boj`, `leetcode`, `jungol`, `theme` (`default`|`dark`|`transparent`), `compact` (`true`/`false`), `animate` (`true`/`false`, default `true` — the one-shot entrance animation; `animate=false` ships a static card).

The CLI takes the same names as flags: `codemaru generate --github <user> [--boj <handle>] [--leetcode <handle>] [--jungol <handle>] --out <path>`.

- Invalid input returns a **visible SVG error card with HTTP 200** (plus an `X-Codemaru-Error: true` header and `Cache-Control: no-store`) so GitHub's image proxy renders the error instead of a broken image; `summary.json` returns a structured `{ "error": ... }` with a 4xx/5xx status.
- Cards send `Cache-Control: public, max-age=300` plus `CDN-Cache-Control` / `Vercel-CDN-Cache-Control` `s-maxage=3600, stale-while-revalidate=86400`, and an `ETag`. A degraded response — a platform that failed, or a stale-fallback copy served during an outage — gets `max-age=60` and `s-maxage=60, stale-while-revalidate=300` instead, so a recovery isn't held back by the edge cache.
- `/api/health` reports `mode`, `scoreVersion`, `version`, whether `kv` and `githubToken` are configured (never their values), and `cacheEntries` (this instance's in-memory cache size). `?deep=true` adds a KV `PING` round-trip as `kvPing` — opt-in, so an uptime monitor polling the plain endpoint isn't paged by a KV outage.

## Fixture mode vs live mode

`FIXTURE_MODE` defaults to **`true`** so local dev and CI need no secrets or network — endpoints serve deterministic fixtures and `/api/health` reports `"mode": "fixture"`.

Set `FIXTURE_MODE=false` for **live mode**: GitHub, solved.ac, LeetCode, and JungOl are fetched concurrently with a per-request timeout (`ADAPTER_TIMEOUT_SECONDS`).

One whole card build is bounded separately by `CARD_BUILD_TIMEOUT_SECONDS` (default 6). It covers the fetch phase only — the request also makes a KV cache read before it and a stale read/write plus the cache write after, each bounded by `KV_TIMEOUT_SECONDS` — so the sum (`KV_TIMEOUT_SECONDS + CARD_BUILD_TIMEOUT_SECONDS + 2 * KV_TIMEOUT_SECONDS`, 9s at the defaults) has to stay below your platform's function timeout (Vercel's default is 10s) with room for scoring and rendering, or the budget never fires. On expiry the platforms that finished are kept and the rest become `unavailable` with a `timed out (card build budget)` note, so the card still renders as `partial`; GitHub stops requesting repository pages cooperatively before the deadline rather than losing the pages it already fetched.

Live GitHub data requires `GITHUB_TOKEN` (the GraphQL API needs auth); without it the GitHub snapshot is `unavailable`.

Each adapter maps any failure (HTTP error, timeout, schema drift, blocked request) to an `unavailable` snapshot, so one platform failing degrades the card to `partial` instead of breaking it.

A computed summary is cached (`CACHE_TTL_SECONDS`) — a degraded or stale one only for `NEGATIVE_CACHE_TTL_SECONDS` (60), and a GitHub handle that doesn't exist for `NOT_FOUND_CACHE_TTL_SECONDS` (600). When Vercel KV (`KV_REST_API_URL` / `KV_REST_API_TOKEN`) is configured the cache is shared across instances, otherwise it falls back to per-instance memory. Either way it's best-effort — a KV outage never affects rendering.

> **Note:** solved.ac sits behind Cloudflare, which rejects plain-Python TLS
> fingerprints (a 403 "Just a moment…" challenge). codemaru fetches it with a
> browser-impersonating TLS client (`curl_cffi`, Chrome profile); if it's ever
> still blocked, the BOJ axis degrades to unavailable. LeetCode's endpoint is
> unofficial and treated as experimental, and JungOl is read from the
> `__data.json` its SvelteKit pages already serve — public, but an internal
> framework format that can change without notice, so its parser is pure and
> tested against saved payloads.

## Logging

`codemaru/telemetry.py` writes one JSON object per line to stdout — on a serverless host that stream is the whole observability surface. Events: `adapter` (one per adapter return), `build` (one per live build, with per-platform statuses), `cache` (hit / miss / rebuild plus the chosen TTL), `kv_error`, and `card_error` (an unexpected failure on `/api/card.svg`, with a traceback).

Only public handles are logged — never request headers, viewer IPs or tokens — and a caught exception contributes its class name, not its message, which can carry a credentialed KV URL — the one deliberate exception is the card route's catch-all, which logs a full traceback because that branch is the only place an unexpected bug surfaces. `configure_logging()` only skips attaching its stdout handler when the root logger already has one (uvicorn, pytest, an embedding process), so it never duplicates someone else's lines; the level is always set, or every event would be dropped on exactly those hosts.

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
- A judge platform starts as one row in `codemaru/adapters/registry.py` plus an adapter module; the registry's own docstring lists everything else a new judge has to touch, and completeness tests fail when one is missed. Never add named judge parameters to scoring / confidence / summary / service signatures — they iterate the registry. Confidence weights are additive and never renormalized, so adding a judge must never lower an existing card.
- Card text is outlined from pre-instanced static fonts. After giving a renderer a new weight, add it to `STATIC_INSTANCES` (`codemaru/render/glyphs.py`) and run `uv run python scripts/instance_fonts.py`; the render tests catch drift in CI by running `scripts/instance_fonts.py --check`.
- Render output is pinned by golden digests. After an intentional visual change, eyeball the SVG and refresh them with `uv run python -m tests.render.golden --update`. The summary JSON is pinned the same way — after an intentional schema or scoring change, refresh it with `uv run python -m tests.core.test_summary_golden --update`.
- Keep PRs small and focused.

## Releasing

1. Tag the release commit `vX.Y.Z` and publish the GitHub release (release-drafter keeps the notes ready as a draft).
2. `major-tag.yml` then moves the floating `v1` tag onto that commit — that's what `uses: bnbong/codemaru@v1` resolves to. A tag can only be *moved* from CI, so the very first `v1` has to be created by hand once (`git tag v1 v1.2.1 && git push origin v1`), or by running the workflow's manual dispatch with an existing tag.
3. `requirements.txt` (what Vercel installs from) is derived from `uv.lock`: `sync-requirements.yml` regenerates and commits it on `main` after a dependency bump, so there's nothing to do by hand.

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
GET /api/health        # 헬스 체크 + 버전·설정·캐시 상태
GET /api/stats/badge   # shields.io 엔드포인트 배지: 임베드한 distinct 사용자 수
```

쿼리 파라미터: `github` (필수), `boj`, `leetcode`, `jungol`, `theme` (`default`|`dark`|`transparent`), `compact` (`true`/`false`), `animate` (`true`/`false`, 기본 `true` — 1회성 등장 애니메이션; `animate=false`면 정적 카드).

CLI도 같은 이름을 플래그로 받습니다: `codemaru generate --github <user> [--boj <핸들>] [--leetcode <핸들>] [--jungol <핸들>] --out <경로>`.

- 잘못된 입력에는 **HTTP 200으로 보이는 SVG 에러 카드**를 반환합니다(`X-Codemaru-Error: true` 헤더와 `Cache-Control: no-store` 포함). GitHub 이미지 프록시가 깨진 이미지 대신 에러를 렌더링하도록 하기 위함입니다. `summary.json`은 4xx/5xx 상태와 함께 구조화된 `{ "error": ... }`를 반환합니다.
- 카드는 `Cache-Control: public, max-age=300`와 함께 `CDN-Cache-Control` / `Vercel-CDN-Cache-Control` `s-maxage=3600, stale-while-revalidate=86400`, 그리고 `ETag`를 보냅니다. degrade된 응답(실패한 플랫폼이 있거나, 장애 중 stale 폴백으로 서빙된 경우)에는 대신 `max-age=60`과 `s-maxage=60, stale-while-revalidate=300`을 보냅니다. 플랫폼이 복구됐는데도 엣지 캐시 때문에 degrade된 카드가 계속 나가는 일을 막기 위함입니다.
- `/api/health`는 `mode`, `scoreVersion`, `version`, `kv`와 `githubToken`의 설정 여부(값은 절대 노출하지 않습니다), `cacheEntries`(이 인스턴스의 인메모리 캐시 크기)를 보고합니다. `?deep=true`를 붙이면 KV `PING` 왕복 결과를 `kvPing`으로 추가합니다. 옵트인이라서, 기본 엔드포인트만 폴링하는 업타임 모니터가 KV 장애로 알림을 받는 일은 없습니다.

## Fixture 모드 vs Live 모드

`FIXTURE_MODE`는 기본값이 **`true`**라 로컬 개발과 CI에 시크릿이나 네트워크가 필요 없습니다. 엔드포인트는 결정적 fixture를 서빙하고 `/api/health`는 `"mode": "fixture"`를 보고합니다.

**Live 모드**는 `FIXTURE_MODE=false`로 켭니다. GitHub, solved.ac, LeetCode, 정올(JungOl)을 요청별 타임아웃(`ADAPTER_TIMEOUT_SECONDS`)으로 동시에 가져옵니다.

카드 빌드 한 번 전체는 `CARD_BUILD_TIMEOUT_SECONDS`(기본 6)로 따로 제한합니다. 이 예산은 fetch 단계만 덮습니다. 요청은 그 앞뒤로 KV 캐시 읽기 한 번, stale 읽기/쓰기와 캐시 쓰기를 더 하고 각각 `KV_TIMEOUT_SECONDS`로 제한되므로, 합계(`KV_TIMEOUT_SECONDS + CARD_BUILD_TIMEOUT_SECONDS + 2 * KV_TIMEOUT_SECONDS`, 기본값이면 9초)가 플랫폼의 함수 타임아웃(Vercel 기본 10초)보다 점수 계산·렌더링 여유를 두고 낮아야 합니다. 그렇지 않으면 예산이 아예 발동하지 않습니다. 시간이 다 되면 이미 끝난 플랫폼은 그대로 두고 나머지는 `timed out (card build budget)` 노트와 함께 `unavailable`이 되므로, 카드는 `partial`로라도 렌더됩니다. GitHub은 데드라인 전에 스스로 저장소 페이지 요청을 멈춰서, 이미 받아 둔 페이지까지 잃지는 않습니다.

라이브 GitHub 데이터에는 `GITHUB_TOKEN`이 필요합니다(GraphQL API는 인증이 필수입니다). 토큰이 없으면 GitHub 스냅샷은 `unavailable`이 됩니다.

각 어댑터는 모든 실패(HTTP 오류, 타임아웃, 스키마 변경, 차단된 요청)를 `unavailable` 스냅샷으로 처리합니다. 그래서 한 플랫폼이 실패해도 카드가 깨지지 않고 `partial`로 degrade됩니다.

계산된 요약은 캐시됩니다(`CACHE_TTL_SECONDS`). degrade됐거나 stale인 결과는 `NEGATIVE_CACHE_TTL_SECONDS`(60)만, 존재하지 않는 GitHub 핸들은 `NOT_FOUND_CACHE_TTL_SECONDS`(600)만 캐시합니다. Vercel KV(`KV_REST_API_URL` / `KV_REST_API_TOKEN`)가 설정돼 있으면 캐시를 인스턴스 간에 공유하고, 없으면 인스턴스 로컬 메모리로 폴백합니다. 어느 쪽이든 best-effort라 KV가 장애를 일으켜도 렌더링에는 영향이 없습니다.

> **참고:** solved.ac는 Cloudflare 뒤에 있어 순수 파이썬 TLS 지문을 거부합니다
> (403 "Just a moment…" 챌린지). codemaru는 브라우저를 모방하는 TLS 클라이언트
> (`curl_cffi`, Chrome 프로필)로 가져옵니다. 그래도 막히면 BOJ 축이 unavailable로
> degrade됩니다. LeetCode 엔드포인트는 비공식이라 실험적으로 취급합니다. 정올은
> SvelteKit 페이지가 이미 내려주는 `__data.json`을 읽습니다. 공개 데이터지만
> 프레임워크 내부 포맷이라 예고 없이 바뀔 수 있어, 파서를 순수 함수로 두고 저장한
> 페이로드로 테스트합니다.

## 로깅

`codemaru/telemetry.py`는 stdout에 JSON 객체를 한 줄에 하나씩 씁니다. 서버리스 환경에서는 이 스트림이 사실상 유일한 관측 수단입니다. 이벤트는 `adapter`(어댑터가 반환할 때마다), `build`(라이브 빌드 1회, 플랫폼별 상태 포함), `cache`(hit / miss / rebuild와 선택된 TTL), `kv_error`, `card_error`(`/api/card.svg`에서 난 예상 못 한 실패, 트레이스백 포함)입니다.

로그에는 공개 핸들만 남깁니다. 요청 헤더, 조회자 IP, 토큰은 기록하지 않고, 잡은 예외는 메시지가 아니라 클래스 이름만 남깁니다(메시지에는 인증 정보가 붙은 KV URL이 들어갈 수 있습니다). 딱 하나 의도적인 예외가 카드 라우트의 catch-all입니다. 예상 못 한 버그가 드러나는 유일한 지점이라 트레이스백을 통째로 남깁니다. `configure_logging()`은 루트 로거에 이미 핸들러가 있으면(uvicorn, pytest, 임베딩한 프로세스) stdout 핸들러만 붙이지 않아서 남이 설정한 로그를 중복 출력하지 않습니다. 레벨은 항상 설정합니다. 그러지 않으면 바로 그런 호스트에서 모든 이벤트가 조용히 사라집니다.

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
- 저지 플랫폼 하나는 `codemaru/adapters/registry.py`의 한 행에 어댑터 모듈을 더한 것으로 시작합니다. 새 저지가 건드려야 하는 나머지 지점은 레지스트리 모듈의 docstring에 정리돼 있고, 빠뜨리면 완결성 테스트가 실패합니다. 점수 계산·confidence·summary·service 시그니처에 저지 이름이 박힌 파라미터를 추가하지 마세요. 모두 레지스트리를 순회합니다. confidence 가중치는 가산식이고 재정규화하지 않으므로, 저지를 추가해서 기존 카드의 점수가 낮아지는 일은 없어야 합니다.
- 카드 텍스트는 미리 인스턴싱해 둔 static 폰트에서 아웃라인으로 뽑습니다. 렌더러에 새 weight를 쓰게 됐다면 `STATIC_INSTANCES`(`codemaru/render/glyphs.py`)에 추가하고 `uv run python scripts/instance_fonts.py`를 실행하세요. CI에서는 렌더 테스트가 `scripts/instance_fonts.py --check`로 드리프트를 잡습니다.
- 렌더 결과는 golden 다이제스트로 고정돼 있습니다. 의도한 시각적 변경을 했다면 SVG를 직접 확인한 뒤 `uv run python -m tests.render.golden --update`로 갱신하세요. summary JSON도 같은 방식으로 고정돼 있으므로, 의도한 스키마나 점수 계산 변경이 있다면 `uv run python -m tests.core.test_summary_golden --update`로 갱신하세요.
- PR은 작고 집중되게 유지하세요.

## 릴리스

1. 릴리스 커밋에 `vX.Y.Z` 태그를 달고 GitHub 릴리스를 publish합니다(release-drafter가 릴리스 노트를 초안으로 준비해 둡니다).
2. 그러면 `major-tag.yml`이 floating 태그 `v1`을 그 커밋으로 옮깁니다. `uses: bnbong/codemaru@v1`이 가리키는 것이 이 태그입니다. CI에서는 태그를 *옮기는* 것만 가능하므로 최초의 `v1`은 한 번 직접 만들어야 합니다(`git tag v1 v1.2.1 && git push origin v1`). 이 워크플로우를 기존 태그로 수동 실행(workflow_dispatch)해도 됩니다.
3. `requirements.txt`(Vercel이 이 파일로 설치합니다)는 `uv.lock`에서 파생된 파일입니다. 의존성이 바뀌면 `sync-requirements.yml`이 `main`에서 다시 생성해 커밋하므로 직접 손댈 일은 없습니다.

