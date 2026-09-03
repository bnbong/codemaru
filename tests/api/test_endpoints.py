import pytest
from fastapi.testclient import TestClient


def test_health(client: TestClient):
    res = client.get("/api/health")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "ok"
    assert body["mode"] == "fixture"
    assert "scoreVersion" in body


def test_health_reports_deploy_facts(client: TestClient):
    from codemaru import __version__

    body = client.get("/api/health").json()
    assert body["version"] == __version__
    assert body["kv"] == "unconfigured"  # neutralized by the test settings fixture
    assert body["githubToken"] in ("configured", "unconfigured")
    assert isinstance(body["cacheEntries"], int)
    # The KV round-trip is opt-in, so an uptime monitor on the plain endpoint is
    # never affected by a KV outage.
    assert "kvPing" not in body


def test_health_reports_token_presence_without_leaking_it(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    from codemaru.settings import get_settings

    monkeypatch.setenv("GITHUB_TOKEN", "ghp_supersecretvalue")
    get_settings.cache_clear()
    res = client.get("/api/health")
    assert res.json()["githubToken"] == "configured"
    assert "ghp_supersecretvalue" not in res.text  # presence only, never the value


def test_health_counts_cache_entries(client: TestClient):
    before = client.get("/api/health").json()["cacheEntries"]
    client.get("/api/card.svg", params={"github": "octocat"})
    assert client.get("/api/health").json()["cacheEntries"] > before


def test_health_deep_reports_unconfigured_kv(client: TestClient):
    body = client.get("/api/health", params={"deep": "true"}).json()
    assert body["kvPing"] == "unconfigured"


def test_health_deep_reports_kv_ok(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    async def ping(base: str, token: str, *args: str) -> str:
        assert args == ("PING",)
        return "PONG"

    monkeypatch.setattr("codemaru.kv.credentials", lambda: ("https://kv.example", "tok"))
    monkeypatch.setattr("codemaru.kv.command", ping)
    assert client.get("/api/health", params={"deep": "true"}).json()["kvPing"] == "ok"


def test_health_deep_survives_a_kv_outage(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    async def boom(*_args: object) -> object:
        raise RuntimeError("kv down")

    monkeypatch.setattr("codemaru.kv.credentials", lambda: ("https://kv.example", "tok"))
    monkeypatch.setattr("codemaru.kv.command", boom)
    body = client.get("/api/health", params={"deep": "true"}).json()
    assert body["kvPing"] == "error"
    assert body["status"] == "ok"  # the probe reports, it never fails the endpoint


def test_favicon_redirects_to_logo(client: TestClient):
    res = client.get("/favicon.ico", follow_redirects=False)
    assert res.status_code in (307, 308)
    assert res.headers["location"] == "/static/codemaru_logo.png"


def test_card_svg_valid(client: TestClient):
    res = client.get("/api/card.svg", params={"github": "octocat", "boj": "baek"})
    assert res.status_code == 200
    assert res.headers["content-type"] == "image/svg+xml; charset=utf-8"
    assert res.text.startswith("<svg")


def test_card_svg_cache_headers_for_camo(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    async def _noop(handle: str) -> None:
        return None

    monkeypatch.setattr("codemaru.web.routes.record_embed", _noop)
    res = client.get(
        "/api/card.svg", params={"github": "octocat"}, headers={"User-Agent": "github-camo/x"}
    )
    assert res.headers["cache-control"] == "public, max-age=300"
    assert "s-maxage=3600" in res.headers["cdn-cache-control"]
    assert "s-maxage=3600" in res.headers["vercel-cdn-cache-control"]
    assert res.headers["etag"]


def test_card_svg_non_camo_is_not_cdn_cached(client: TestClient):
    # Non-Camo requests (previews / direct opens) must not populate the shared
    # CDN entry, or they would shadow the Camo request that does the counting.
    res = client.get("/api/card.svg", params={"github": "octocat"})
    assert res.headers["cache-control"] == "no-store"
    assert "cdn-cache-control" not in res.headers


def test_stats_badge_returns_shields_schema(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    from codemaru import analytics

    monkeypatch.setattr(analytics, "_credentials", lambda: None)  # no KV -> 0
    res = client.get("/api/stats/badge")
    assert res.status_code == 200
    data = res.json()
    assert data["schemaVersion"] == 1
    assert data["label"] == "users"
    assert data["message"] == "0"
    assert data["color"] == "f778ba"  # Maru tier accent
    # CDN cache headers (mirrors the card endpoint) so shields/Vercel cache it.
    assert "s-maxage=600" in res.headers["cdn-cache-control"]
    assert "s-maxage=600" in res.headers["vercel-cdn-cache-control"]


def test_card_svg_records_embed_for_camo_requests(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    recorded: list[str] = []

    async def _spy(handle: str) -> None:
        recorded.append(handle)

    monkeypatch.setattr("codemaru.web.routes.record_embed", _spy)
    res = client.get(
        "/api/card.svg",
        params={"github": "octocat"},
        headers={"User-Agent": "github-camo/abc123"},
    )
    assert res.status_code == 200
    assert recorded == ["octocat"]  # background task ran (TestClient awaits it)
    assert "s-maxage=3600" in res.headers["cdn-cache-control"]  # cached for viewers


def test_card_svg_skips_embed_for_non_camo_requests(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    recorded: list[str] = []

    async def _spy(handle: str) -> None:
        recorded.append(handle)

    monkeypatch.setattr("codemaru.web.routes.record_embed", _spy)
    res = client.get(
        "/api/card.svg",
        params={"github": "octocat"},
        headers={"User-Agent": "Mozilla/5.0 (preview)"},
    )
    assert res.status_code == 200
    assert recorded == []
    assert res.headers["cache-control"] == "no-store"


def test_card_svg_compact(client: TestClient):
    res = client.get("/api/card.svg", params={"github": "octocat", "compact": "true"})
    assert res.status_code == 200
    assert 'viewBox="0 0 250 270"' in res.text


def test_card_svg_animation_default_and_optout(client: TestClient):
    animated = client.get("/api/card.svg", params={"github": "octocat"})
    assert "<style>" in animated.text  # entrance animation on by default
    static = client.get("/api/card.svg", params={"github": "octocat", "animate": "false"})
    assert static.status_code == 200
    assert "<style>" not in static.text  # opt-out ships a static card


def test_card_svg_invalid_returns_error_card_with_200(client: TestClient):
    # 200 (not 4xx) so GitHub's Camo proxy shows the error card, not a broken image.
    res = client.get("/api/card.svg", params={"github": "foo_bar"})
    assert res.status_code == 200
    assert res.headers["content-type"] == "image/svg+xml; charset=utf-8"
    assert res.headers["x-codemaru-error"] == "true"
    assert res.headers["cache-control"] == "no-store"
    assert res.text.startswith("<svg")
    assert "github" in res.text


def test_card_svg_missing_github_returns_error_card(client: TestClient):
    res = client.get("/api/card.svg")
    assert res.status_code == 200
    assert res.headers["x-codemaru-error"] == "true"
    assert res.text.startswith("<svg")


def test_card_svg_invalid_compact_returns_error_card(client: TestClient):
    res = client.get("/api/card.svg", params={"github": "octocat", "compact": "ture"})
    assert res.status_code == 200
    assert res.headers["x-codemaru-error"] == "true"
    assert "compact" in res.text


def test_card_svg_error_card_keeps_the_compact_dimensions(client: TestClient):
    # A compact embed reserves 250x270 in the README; a 640x300 error card there
    # would blow out the layout.
    res = client.get("/api/card.svg", params={"github": "bad_name", "compact": "true"})
    assert res.headers["x-codemaru-error"] == "true"
    assert 'viewBox="0 0 250 270"' in res.text


def test_card_svg_error_card_defaults_to_the_full_size(client: TestClient):
    res = client.get("/api/card.svg", params={"github": "bad_name"})
    assert res.headers["x-codemaru-error"] == "true"
    assert 'viewBox="0 0 640 300"' in res.text


def test_card_svg_unexpected_error_returns_error_card_not_500(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    # An uncaught exception would be a FastAPI 500 -> a broken image in a README.
    async def boom(profile: object) -> object:
        raise RuntimeError("something internal exploded")

    monkeypatch.setattr("codemaru.web.routes.get_summary", boom)
    res = client.get("/api/card.svg", params={"github": "octocat"})
    assert res.status_code == 200
    assert res.headers["x-codemaru-error"] == "true"
    assert res.headers["cache-control"] == "no-store"  # retried on the next request
    assert "temporarily unavailable" in res.text
    assert "something internal exploded" not in res.text  # internals never leak


def test_card_svg_unexpected_error_keeps_compact(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    async def boom(profile: object) -> object:
        raise RuntimeError("boom")

    monkeypatch.setattr("codemaru.web.routes.get_summary", boom)
    res = client.get("/api/card.svg", params={"github": "octocat", "compact": "true"})
    assert 'viewBox="0 0 250 270"' in res.text


def test_summary_json_valid(client: TestClient):
    res = client.get(
        "/api/summary.json",
        params={"github": "octocat", "boj": "baek", "leetcode": "lc", "jungol": "jo"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["input"]["github"] == "octocat"
    assert "confidence" in data["scores"]  # confidence kept in JSON, not on card
    assert data["scores"]["scoreVersion"]
    assert len(data["strengths"]) == 3


def test_summary_json_invalid_returns_structured_error(client: TestClient):
    res = client.get("/api/summary.json", params={"github": "-bad"})
    assert res.status_code == 400
    assert "error" in res.json()


def test_summary_json_invalid_compact_returns_400(client: TestClient):
    res = client.get("/api/summary.json", params={"github": "octocat", "compact": "maybe"})
    assert res.status_code == 400
    assert "compact" in res.json()["error"]


def test_summary_json_does_not_swallow_unexpected_errors(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    # Deliberately unlike the card: a JSON 500 is honest and easier to debug, and
    # no README renders it as a broken image.
    async def boom(profile: object) -> object:
        raise RuntimeError("something internal exploded")

    monkeypatch.setattr("codemaru.web.routes.get_summary", boom)
    with pytest.raises(RuntimeError):
        client.get("/api/summary.json", params={"github": "octocat"})


def test_summary_json_ignores_unknown_params(client: TestClient):
    res = client.get("/api/summary.json", params={"github": "octocat", "refresh": "1730000000"})
    assert res.status_code == 200


def test_index_page_renders_demo_preview(client: TestClient):
    res = client.get("/")
    assert res.status_code == 200
    assert "text/html" in res.headers["content-type"]
    assert "codemaru" in res.text
    assert "/api/card.svg?github=codemaru-demo" in res.text
    # The GitHub Action snippet is published, so it's shown as copyable (no
    # "coming soon" placeholder) and references the real action.
    assert "coming soon" not in res.text
    assert "bnbong/codemaru@v1" in res.text


def test_index_no_js_form_fallback_shows_preview(client: TestClient):
    res = client.get("/", params={"github": "octocat", "theme": "dark"})
    assert res.status_code == 200
    assert "/api/card.svg?github=octocat" in res.text


def test_index_invalid_input_shows_error(client: TestClient):
    res = client.get("/", params={"github": "bad_name"})
    assert res.status_code == 200
    assert "github" in res.text


def test_index_accepts_animate_and_carries_it_into_the_snippets(client: TestClient):
    res = client.get("/", params={"github": "octocat", "animate": "false"})
    assert res.status_code == 200
    # Both the live preview and the copyable embed snippets must reflect the
    # opt-out, or the generator would show something the README won't produce.
    assert "/api/card.svg?github=octocat&amp;animate=false" in res.text


def test_index_animation_defaults_to_on(client: TestClient):
    res = client.get("/", params={"github": "octocat"})
    assert res.status_code == 200
    # Animation is the default, so it never rides in the URL.
    assert "animate=false" not in res.text


# --- fixture-vs-live mode reporting (orchestration tests live in test_live_mode) ---


def test_health_reports_live_when_fixture_mode_off(client: TestClient, live_mode: None):
    assert client.get("/api/health").json()["mode"] == "live"


def test_summary_json_reports_jungol_input_and_snapshot(client: TestClient):
    res = client.get("/api/summary.json", params={"github": "octocat", "jungol": "jo"})
    assert res.status_code == 200
    data = res.json()
    assert data["input"]["jungol"] == "jo"
    assert data["snapshots"]["jungol"]["handle"] == "jo"


def test_summary_json_rejects_an_invalid_jungol_handle(client: TestClient):
    res = client.get("/api/summary.json", params={"github": "octocat", "jungol": "bad handle"})
    assert res.status_code == 400
    assert "jungol" in res.json()["error"]


def test_card_svg_accepts_a_jungol_handle(client: TestClient):
    res = client.get("/api/card.svg", params={"github": "octocat", "jungol": "jo"})
    assert res.status_code == 200
    assert "x-codemaru-error" not in res.headers
    assert res.text.startswith("<svg")


def test_index_renders_a_jungol_field_carrying_the_submitted_value(client: TestClient):
    res = client.get("/", params={"github": "octocat", "jungol": "jo"})
    assert res.status_code == 200
    assert 'id="jungol"' in res.text
    assert 'value="jo"' in res.text
    assert "jungol=jo" in res.text  # the preview URL and the copy snippets


def test_index_demo_prefills_the_jungol_handle(client: TestClient):
    from codemaru.fixtures.demo import DEMO_INPUT

    res = client.get("/")
    assert f'value="{DEMO_INPUT.jungol}"' in res.text
