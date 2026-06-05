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


def test_card_svg_cache_headers(client: TestClient):
    res = client.get("/api/card.svg", params={"github": "octocat"})
    assert res.headers["cache-control"] == "public, max-age=300"
    assert "s-maxage=3600" in res.headers["cdn-cache-control"]
    assert "s-maxage=3600" in res.headers["vercel-cdn-cache-control"]
    assert res.headers["etag"]


def test_card_svg_compact(client: TestClient):
    res = client.get("/api/card.svg", params={"github": "octocat", "compact": "true"})
    assert res.status_code == 200
    assert 'viewBox="0 0 250 256"' in res.text


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
    # GitHub Action snippet is hidden behind "coming soon" until it exists.
    assert "coming soon" in res.text


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
