import pytest
from fastapi.testclient import TestClient


def test_health(client: TestClient):
    res = client.get("/api/health")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "ok"
    assert body["mode"] == "fixture"
    assert "scoreVersion" in body


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


def test_summary_json_valid(client: TestClient):
    res = client.get(
        "/api/summary.json",
        params={"github": "octocat", "boj": "baek", "leetcode": "lc"},
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


# --- fixture-vs-live mode reporting (orchestration tests live in test_live_mode) ---


def test_health_reports_live_when_fixture_mode_off(client: TestClient, live_mode: None):
    assert client.get("/api/health").json()["mode"] == "live"
