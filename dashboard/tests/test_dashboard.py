"""Tests for the canonical SharipovAI Web2 interface and stable APIs."""
from __future__ import annotations

from types import SimpleNamespace

from fastapi.testclient import TestClient

from dashboard import create_app
from learning_engine import LearningSummary


VISIBLE_PAGES = (
    "/",
    "/ai-decision",
    "/market",
    "/news",
    "/portfolio",
    "/paper-trading",
    "/learning",
    "/self-analysis",
    "/stress-lab",
    "/ai-improvement",
    "/reports",
    "/ai-control-center",
    "/settings",
)


def _runner_factory():
    class Runner:
        def run(self):
            return SimpleNamespace(
                decision="BUY",
                confidence=95.0,
                risk_level="LOW",
                portfolio_value=10000.0,
                paper_cash=9500.0,
                paper_equity=10000.0,
                paper_pnl=500.0,
                open_positions=1,
                consensus="UNANIMOUS",
                consensus_agreement=100.0,
                reason="Verified test runner",
                report="Verified test report",
                learning_summary=LearningSummary(total_trades=1, win_rate=100.0, average_return=5.0),
            )

    return Runner()


def _failing_runner_factory():
    class Runner:
        def run(self):
            raise RuntimeError("runner unavailable")

    return Runner()


def client(factory=_runner_factory) -> TestClient:
    return TestClient(create_app(runner_factory=factory))


def test_app_creates_successfully() -> None:
    app = create_app(runner_factory=_runner_factory)
    assert app.title == "SharipovAI OS"


def test_all_legacy_page_urls_serve_canonical_web2_shell() -> None:
    test_client = client()
    for path in VISIBLE_PAGES:
        response = test_client.get(path)
        assert response.status_code == 200, path
        assert "SharipovAI — торговая система" in response.text
        assert 'id="nav"' in response.text
        assert 'id="content"' in response.text
        assert "/static/web2/" in response.text


def test_web2_contains_all_primary_sections_once() -> None:
    response = client().get("/")
    assert response.status_code == 200
    for page in (
        "overview", "market", "decision", "portfolio", "trades", "bots", "chat",
        "news", "risk", "bybit", "learning", "control", "evidence", "virtual",
        "reports", "settings",
    ):
        assert response.text.count(f'data-page="{page}"') == 1


def test_old_dashboard_template_is_not_required() -> None:
    response = client().get("/stress-lab?lang=en")
    assert response.status_code == 200
    assert "TemplateNotFound" not in response.text
    assert "os-sidebar" not in response.text
    assert "hero-decision" not in response.text


def test_health_endpoints_work() -> None:
    test_client = client()
    health = test_client.get("/health")
    api_health = test_client.get("/api/health")
    assert health.status_code == 200
    assert api_health.status_code == 200
    assert health.json()["status"] == "ok"
    assert api_health.json()["status"] == "ok"


def test_api_run_endpoint_uses_runner_values() -> None:
    response = client().get("/api/run")
    assert response.status_code == 200
    payload = response.json()
    assert payload["decision"] == "BUY"
    assert payload["risk_level"] == "LOW"
    assert payload["paper_cash"] == 9500.0
    assert payload["paper_equity"] == 10000.0
    assert payload["learning_summary"]["total_trades"] == 1


def test_runner_failure_returns_safe_api_state_and_web2_still_loads() -> None:
    test_client = client(_failing_runner_factory)
    page = test_client.get("/")
    run = test_client.get("/api/run")
    assert page.status_code == 200
    assert "SharipovAI — торговая система" in page.text
    assert run.status_code == 200
    assert run.json()["decision"] in {"WATCH", "NO DECISION"}


def test_translation_endpoint_supports_three_languages_and_fallback() -> None:
    test_client = client()
    assert test_client.get("/api/translations/ru").json()["overview"] == "Обзор"
    assert test_client.get("/api/translations/en").json()["overview"] == "Overview"
    assert test_client.get("/api/translations/uz").json()["overview"]
    assert test_client.get("/api/translations/de").json()["overview"] == "Обзор"


def test_stress_lab_scenarios_are_deterministic_and_safe() -> None:
    test_client = client()
    scenarios = test_client.get("/api/stress-lab/scenarios")
    result = test_client.post("/api/stress-lab/run", json={"scenario": "market_crash_50"})
    assert scenarios.status_code == 200
    assert result.status_code == 200
    ids = {item["id"] for item in scenarios.json()["scenarios"]}
    assert {"btc_drop_20", "market_crash_50", "virtual_capital_loss_10"} <= ids
    payload = result.json()
    assert payload["scenario"] == "market_crash_50"
    assert payload["after"]["loss_amount"] > 0
    assert "block new BUY decisions" in payload["protective_measures"]


def test_ai_improvement_api_remains_available() -> None:
    response = client().get("/api/ai-improvement")
    assert response.status_code == 200
    payload = response.json()
    assert isinstance(payload["recommendations"], list)
    assert payload["recommendations"]


def test_logo_and_favicon_routes_work() -> None:
    test_client = client()
    favicon = test_client.get("/favicon.ico")
    logo = test_client.get("/logo.svg")
    assert favicon.status_code == 200
    assert logo.status_code == 200
    assert "image/svg" in favicon.headers["content-type"]
    assert "image/svg" in logo.headers["content-type"]


def test_web2_assets_referenced_by_index_exist() -> None:
    from pathlib import Path
    import re

    root = Path(__file__).resolve().parents[1] / "static" / "web2"
    html = (root / "index.html").read_text(encoding="utf-8")
    assets = re.findall(r'(?:src|href)="/static/web2/([^"?]+)', html)
    assert assets
    missing = [asset for asset in assets if not (root / asset).is_file()]
    assert missing == []
