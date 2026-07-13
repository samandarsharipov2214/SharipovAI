"""Tests for the current FastAPI + Web2 SharipovAI interface."""
from __future__ import annotations

from fastapi.testclient import TestClient

from dashboard import create_app
from learning_engine import LearningSummary
from runner import RunnerOutput

VISIBLE_PAGES = (
    "/", "/ai-decision", "/market", "/news", "/portfolio", "/paper-trading",
    "/learning", "/self-analysis", "/stress-lab", "/ai-improvement", "/reports",
    "/ai-control-center", "/settings",
)


def _assert_web2_shell(text: str) -> None:
    assert "SharipovAI — торговая система" in text
    assert 'id="nav"' in text
    assert 'id="content"' in text
    assert "/static/web2/navigation_coordinator_v23.js" in text
    assert "/static/web2/truth_guard.js" in text


def test_app_creates_successfully() -> None:
    assert create_app(runner_factory=_runner_factory).title == "SharipovAI OS"


def test_all_visible_pages_serve_one_web2_shell() -> None:
    client = TestClient(create_app(runner_factory=_runner_factory))
    for path in VISIBLE_PAGES:
        response = client.get(path)
        assert response.status_code == 200
        _assert_web2_shell(response.text)


def test_web2_shell_exposes_current_navigation_and_languages() -> None:
    response = TestClient(create_app(runner_factory=_runner_factory)).get("/")
    assert response.status_code == 200
    for page_id in (
        "overview", "market", "decision", "portfolio", "trades", "bots", "chat",
        "news", "risk", "bybit", "learning", "control", "evidence", "virtual",
        "reports", "settings",
    ):
        assert f'data-page="{page_id}"' in response.text
    for language in ("ru", "en", "uz"):
        assert f'data-lang="{language}"' in response.text
    assert "Привет, Самандар" in response.text


def test_health_endpoints_work() -> None:
    client = TestClient(create_app(runner_factory=_runner_factory))
    assert client.get("/health").json()["status"] == "ok"
    assert client.get("/api/health").json()["status"] == "ok"


def test_api_run_endpoint_keeps_runner_data_in_api_not_static_html() -> None:
    response = TestClient(create_app(runner_factory=_runner_factory)).get("/api/run")
    assert response.status_code == 200
    payload = response.json()
    assert payload["decision"] == "BUY"
    assert payload["risk_level"] == "LOW"
    assert payload["paper_cash"] == 9500.0
    assert payload["paper_equity"] == 10000.0
    assert payload["learning_summary"]["total_trades"] == 1


def test_translation_endpoint_works() -> None:
    response = TestClient(create_app(runner_factory=_runner_factory)).get("/api/translations/en")
    assert response.status_code == 200
    assert response.json()["overview"] == "Overview"


def test_crash_test_endpoints_are_safe_simulations() -> None:
    client = TestClient(create_app(runner_factory=_runner_factory))
    assert client.get("/api/crash-test").status_code == 200
    response = client.post("/api/crash-test", json={"scenario": "market_crash_50"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["scenario"] == "market_crash_50"
    assert payload["loss_percent"] == 50.0
    assert "block new BUY decisions" in payload["protective_measures"]


def test_stress_lab_scenarios_and_protection_work() -> None:
    client = TestClient(create_app(runner_factory=_runner_factory))
    scenarios = client.get("/api/stress-lab/scenarios")
    assert scenarios.status_code == 200
    ids = {item["id"] for item in scenarios.json()["scenarios"]}
    assert {"btc_drop_20", "market_crash_50", "virtual_capital_loss_10"} <= ids

    response = client.post(
        "/api/stress-lab/run",
        json={
            "scenario": "market_crash_50",
            "starting_virtual_capital": 10000,
            "current_exposure": 100,
            "maximum_acceptable_drawdown": 10,
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["after"]["loss_percent"] >= 10
    assert payload["classification"] == "capital protection triggered"
    assert "pause trading if drawdown limit exceeded" in payload["ai_reaction"]


def test_ai_improvement_api_is_read_only() -> None:
    response = TestClient(create_app(runner_factory=_runner_factory)).get("/api/ai-improvement")
    assert response.status_code == 200
    recommendations = response.json()["recommendations"]
    assert recommendations
    assert all(item.get("automatic") is not True for item in recommendations)


def test_logo_and_favicon_routes_work() -> None:
    client = TestClient(create_app(runner_factory=_runner_factory))
    favicon = client.get("/favicon.ico")
    logo = client.get("/logo.svg")
    assert favicon.status_code == 200
    assert logo.status_code == 200
    assert "image/svg" in favicon.headers["content-type"]
    assert "image/svg" in logo.headers["content-type"]


def test_runner_failure_does_not_break_static_web2_shell() -> None:
    response = TestClient(create_app(runner_factory=_failing_runner_factory)).get("/")
    assert response.status_code == 200
    _assert_web2_shell(response.text)


def test_partial_runner_does_not_break_static_web2_shell() -> None:
    response = TestClient(create_app(runner_factory=_partial_runner_factory)).get("/")
    assert response.status_code == 200
    _assert_web2_shell(response.text)


def test_visible_product_does_not_call_itself_dashboard() -> None:
    response = TestClient(create_app(runner_factory=_runner_factory)).get("/")
    assert response.status_code == 200
    assert "Dashboard" not in response.text


class _FakeRunner:
    def run(self) -> RunnerOutput:
        return RunnerOutput(
            decision="BUY",
            confidence=88.0,
            risk_level="LOW",
            portfolio_value=10000.0,
            paper_cash=9500.0,
            paper_equity=10000.0,
            learning_summary=LearningSummary(
                total_trades=1,
                wins=1,
                losses=0,
                win_rate=100.0,
                average_profit=0.0,
                average_loss=0.0,
                best_trade=0.0,
                worst_trade=0.0,
                recommendations=["More historical data is required."],
            ),
            report="SharipovAI runner completed.",
            reason="Test decision reason.",
            consensus="UNANIMOUS",
            consensus_agreement=100.0,
            paper_pnl=0.0,
            open_positions=1,
        )


class _FailingRunner:
    def run(self) -> RunnerOutput:
        raise RuntimeError("runner unavailable")


class _PartialRunner:
    def run(self) -> object:
        return object()


def _runner_factory() -> _FakeRunner:
    return _FakeRunner()


def _failing_runner_factory() -> _FailingRunner:
    return _FailingRunner()


def _partial_runner_factory() -> _PartialRunner:
    return _PartialRunner()
