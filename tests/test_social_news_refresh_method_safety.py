from __future__ import annotations

import pytest
from fastapi import FastAPI, HTTPException

import dashboard.social_news_api as social_news_api


def _route_endpoint(app: FastAPI, path: str, method: str):
    return next(
        route.endpoint
        for route in app.routes
        if getattr(route, "path", None) == path
        and method in getattr(route, "methods", set())
    )


def test_get_rss_refresh_is_non_mutating_and_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    def unexpected_refresh(**_kwargs):
        raise AssertionError("GET must never invoke refresh_news_now")

    monkeypatch.setattr(social_news_api, "refresh_news_now", unexpected_refresh)
    app = FastAPI()
    social_news_api.install_social_news_api(app)
    endpoint = _route_endpoint(app, "/api/social-news/rss/refresh", "GET")

    with pytest.raises(HTTPException) as exc_info:
        endpoint()

    assert exc_info.value.status_code == 405
    assert exc_info.value.headers == {"Allow": "POST"}
    assert exc_info.value.detail["status"] == "method_not_allowed"


def test_post_rss_refresh_remains_the_mutating_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, object]] = []

    def fake_refresh(**kwargs):
        calls.append(kwargs)
        return {"status": "ok", "refreshed": True}

    monkeypatch.setattr(social_news_api, "refresh_news_now", fake_refresh)
    app = FastAPI()
    social_news_api.install_social_news_api(app)
    endpoint = _route_endpoint(app, "/api/social-news/rss/refresh", "POST")

    result = endpoint({"limit_per_source": 3})

    assert result == {"status": "ok", "refreshed": True}
    assert calls == [{"reason": "manual_api_rss_refresh", "limit_per_source": 3}]
