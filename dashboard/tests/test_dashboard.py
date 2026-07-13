"""Tests for the current FastAPI + Web2 SharipovAI interface."""

from __future__ import annotations

from fastapi.testclient import TestClient

from dashboard import create_app
from learning_engine import LearningSummary
from runner import RunnerOutput

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

WEB2_SHELL_MARKERS = (
    "SharipovAI — торговая система",
    'id="nav"',
    'id="content"',
    "navigation_coordinator_v23.js",
    "truth_guard.js",
)


def test_app_creates_successfully() -> None:
    app = create_app(runner_factory=_runner_factory)
    assert app.title == "SharipovAI OS"


def test_all_visible_pages_return_success() -> None:
    client = TestClient(create_app(runner_factory=_runner_factory))
    for path in VISIBLE_PAGES:
        response = client.get(path)
        assert response.status_code == 200, path
        assert response.text.strip(), path


def test_overview_serves_current_web2_shell() -> None:
    response = TestClient(create_app(runner_factory=_runner_factory)).get("/?lang=ru")
    assert response.status_code == 200
    for marker in WEB2_SHELL_MARKERS:
        assert marker in response.text
    assert "Центр управления" in response.text
    assert "Обзор" in response.text
    assert "Центр рисков" in response.text
    assert "Хранилище доказательств" in response.text
    assert "Виртуальный счёт" in response.text


def test_web2_language_controls_are_present() -> None:
    text = TestClient(create_app(runner_factory=_runner_factory)).get("/").text
    assert 'data-lang="ru"' in text
    assert 'data-lang="en"' in text
    assert 'data-lang="uz"' in text


def test_web2_uses_single_navigation_owner() -> None:
    text = TestClient(create_app(runner_factory=_runner_factory)).get("/").text
    assert text.count("navigation_coordinator_v23.js") == 1
    assert 'data-page="stress' not in text
    assert 'data-page="risk"' in text
    assert "Панель краш-теста" not in text


def test_health_endpoints_work() -> None:
    client = TestClient(create_app(runner_factory=_runner_factory))
    assert client.get("/health").json() == {"status": "ok"}
    assert client.get("/api/health").json() == {"status": "ok"}


def test_api_run_endpoint_returns_runner_values() -> None:
    response = TestClient(create_app(runner_factory=_runner_factory)).get("/api/run")
    assert response.status_code == 200
    payload = response.json()
    assert payload["decision"] == "BUY"
    assert payload["risk_level"] == "LOW"
    assert payload["paper_cash"] == 9500.0
    assert payload["paper_equity"] == 10000.0
    assert payload["learning_summary"]["total_trades"] == 1


def test_runner_failure_returns_safe_api_fallback() -> None:
    response = TestClient(create_app(runner_factory=_failing_runner_factory)).get("/api/run")
    assert response.status_code == 200
    payload = response.json()
    assert payload["decision"] == "WATCH"
    assert payload["risk_level"] == "LOW"
    assert "Runner временно недоступен" in payload["report"]


def test_missing_runner_data_returns_safe_defaults() -> None:
    response = TestClient(create_app(runner_factory=_partial_runner_factory)).get("/api/run")
    assert response.status_code == 200
    payload = response.json()
    assert payload["decision"] == "WATCH"
    assert payload["paper_equity"] == 10000.0


def test_translation_endpoint_works() -> None:
    response = TestClient(create_app(runner_factory=_runner_factory)).get("/api/translations/en")
    assert response.status_code == 200
    assert response.json()["overview"] == "Overview"


def test_crash_test_endpoints_remain_safe_and_deterministic() -> None:
    client = TestClient(create_app(runner_factory=_runner_factory))
    assert client.get("/api/crash-test").status_code == 200
    response = client.post("/api/crash-test", json={"scenario": "market_crash_50"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["scenario"] == "market_crash_50"
    assert payload["after"]["loss_amount"] > 0
    assert payload["classification"] == "capital protection triggered"


def test_stress_lab_scenarios_and_run_api_work() -> None:
    client = TestClient(create_app(runner_factory=_runner_factory))
    scenarios = client.get("/api/stress-lab/scenarios").json()["scenarios"]
    ids = {item["id"] for item in scenarios}
    assert {"btc_drop_20", "market_crash_50", "virtual_capital_loss_10"} <= ids

    payload = client.post(
        "/api/stress-lab/run",
        json={
            "scenario": "market_crash_50",
            "starting_virtual_capital": 10000,
            "current_exposure": 100,
            "maximum_acceptable_drawdown": 10,
        },
    ).json()
    assert payload["after"]["loss_percent"] >= 10
    assert payload["classification"] == "capital protection triggered"
    assert payload["capital_after"] < payload["capital_before"]


def test_ai_improvement_api_is_read_only() -> None:
    payload = TestClient(create_app(runner_factory=_runner_factory)).get("/api/ai-improvement").json()
    assert payload["status"] == "ok"
    assert payload["recommendations"]
    assert all(item.get("automatic") is False for item in payload["recommendations"])


def test_logo_and_favicon_routes_work() -> None:
    client = TestClient(create_app(runner_factory=_runner_factory))
    favicon = client.get("/favicon.ico")
    logo = client.get("/logo.svg")
    assert favicon.status_code == 200
    assert logo.status_code == 200
    assert "image/svg" in favicon.headers["content-type"]
    assert "image/svg" in logo.headers["content-type"]


def test_visible_product_identity_does_not_use_dashboard_naming() -> None:
    response = TestClient(create_app(runner_factory=_runner_factory)).get("/")
    assert response.status_code == 200
    assert "SharipovAI" in response.text
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
