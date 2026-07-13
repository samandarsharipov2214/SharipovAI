"""Tests for the current FastAPI + Web2 SharipovAI interface."""

from __future__ import annotations

from fastapi.testclient import TestClient

from dashboard import create_app
from learning_engine import LearningSummary
from runner import RunnerOutput

SPA_PAGES = (
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
    "/settings",
)


def _assert_web2_shell(text: str) -> None:
    assert "SharipovAI — торговая система" in text
    assert 'class="app"' in text
    assert 'id="nav"' in text
    assert 'id="content"' in text
    assert 'data-page="overview"' in text
    assert 'data-page="settings"' in text
    assert "/static/web2/web2.js" in text
    assert "/static/web2/operations_center_v20.js" in text


def test_app_creates_successfully() -> None:
    app = create_app(runner_factory=_runner_factory)
    assert app.title == "SharipovAI OS"


def test_all_spa_pages_return_current_web2_shell() -> None:
    client = TestClient(create_app(runner_factory=_runner_factory))
    for path in SPA_PAGES:
        response = client.get(path)
        assert response.status_code == 200
        _assert_web2_shell(response.text)


def test_overview_page_renders_current_live_interface_shell() -> None:
    response = TestClient(create_app(runner_factory=_runner_factory)).get("/?lang=ru")
    assert response.status_code == 200
    _assert_web2_shell(response.text)
    assert "Центр управления" in response.text
    assert "Привет, Самандар" in response.text
    assert 'data-page="decision"' in response.text
    assert 'data-page="portfolio"' in response.text


def test_runner_values_are_exposed_by_api_not_fabricated_in_static_html() -> None:
    client = TestClient(create_app(runner_factory=_runner_factory))
    payload = client.get("/api/run").json()
    assert payload["decision"] == "BUY"
    assert payload["risk_level"] == "LOW"
    assert payload["paper_cash"] == 9500.0
    assert payload["paper_equity"] == 10000.0
    assert payload["learning_summary"]["total_trades"] == 1


def test_health_endpoints_work() -> None:
    client = TestClient(create_app(runner_factory=_runner_factory))
    assert client.get("/health").json() == {"status": "ok"}
    assert client.get("/api/health").json() == {"status": "ok"}


def test_translation_endpoint_works() -> None:
    response = TestClient(create_app(runner_factory=_runner_factory)).get("/api/translations/en")
    assert response.status_code == 200
    assert response.json()["overview"] == "Overview"


def test_crash_test_endpoints_work() -> None:
    client = TestClient(create_app(runner_factory=_runner_factory))
    get_response = client.get("/api/crash-test")
    post_response = client.post("/api/crash-test", json={"scenario": "market_crash_50"})
    assert get_response.status_code == 200
    assert post_response.status_code == 200
    payload = post_response.json()
    assert payload["scenario"] == "market_crash_50"
    assert payload["loss_percent"] == 50.0
    assert "block new BUY decisions" in payload["protective_measures"]


def test_stress_lab_page_uses_spa_and_scenario_api() -> None:
    client = TestClient(create_app(runner_factory=_runner_factory))
    page = client.get("/stress-lab?lang=en")
    assert page.status_code == 200
    _assert_web2_shell(page.text)
    assert 'data-page="risk"' in page.text
    scenarios = client.get("/api/stress-lab/scenarios").json()["scenarios"]
    assert {"id": "btc_drop_20", "label": "BTC price drop 20%"} in scenarios
    assert {"id": "market_crash_50", "label": "Market crash 50%"} in scenarios
    assert {"id": "virtual_capital_loss_10", "label": "Virtual capital loss 10%"} in scenarios


def test_stress_lab_btc_drop_20_scenario_works() -> None:
    payload = TestClient(create_app(runner_factory=_runner_factory)).post(
        "/api/stress-lab/run", json={"scenario": "btc_drop_20"}
    ).json()
    assert payload["scenario"] == "btc_drop_20"
    assert payload["parameters"]["price_drop_percent"] == 20.0
    assert payload["after"]["loss_percent"] >= 0
    assert "switch to WATCH mode" in payload["ai_reaction"]
    assert "risk limit applied" in payload["protective_measures"]


def test_stress_lab_market_crash_50_scenario_works() -> None:
    payload = TestClient(create_app(runner_factory=_runner_factory)).post(
        "/api/stress-lab/run", json={"scenario": "market_crash_50"}
    ).json()
    assert payload["parameters"]["price_drop_percent"] == 50.0
    assert payload["after"]["loss_amount"] > 0


def test_stress_lab_virtual_capital_loss_scenario_works() -> None:
    payload = TestClient(create_app(runner_factory=_runner_factory)).post(
        "/api/stress-lab/run", json={"scenario": "virtual_capital_loss_10"}
    ).json()
    assert payload["parameters"]["capital_loss_percent"] == 10.0


def test_stress_lab_critical_drawdown_triggers_protection() -> None:
    payload = TestClient(create_app(runner_factory=_runner_factory)).post(
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
    assert "pause trading if drawdown limit exceeded" in payload["ai_reaction"]


def test_translations_are_served_by_api_for_all_languages() -> None:
    client = TestClient(create_app(runner_factory=_runner_factory))
    ru = client.get("/api/translations/ru").json()
    en = client.get("/api/translations/en").json()
    uz = client.get("/api/translations/uz").json()
    assert ru["overview"] == "Обзор"
    assert ru["stress_lab"] == "Стресс-лаборатория"
    assert en["overview"] == "Overview"
    assert en["ai_improvement"] == "AI Improvement"
    assert uz["overview"] == "Umumiy ko'rinish"
    assert uz["stress_lab"] == "Stress laboratoriyasi"


def test_invalid_language_falls_back_to_russian() -> None:
    payload = TestClient(create_app(runner_factory=_runner_factory)).get("/api/translations/de").json()
    assert payload["overview"] == "Обзор"


def test_ai_improvement_spa_and_compatibility_api_are_current() -> None:
    client = TestClient(create_app(runner_factory=_runner_factory))
    page = client.get("/ai-improvement?lang=en")
    api = client.get("/api/ai-improvement")
    assert page.status_code == 200
    _assert_web2_shell(page.text)
    assert api.status_code == 200
    recommendations = api.json()["recommendations"]
    assert recommendations
    assert recommendations[0]["title"] == "Add Macro Agent"
    assert recommendations[0]["status"] == "recommended"


def test_logo_and_favicon_routes_work() -> None:
    client = TestClient(create_app(runner_factory=_runner_factory))
    favicon = client.get("/favicon.ico")
    logo = client.get("/logo.svg")
    assert favicon.status_code == 200
    assert logo.status_code == 200
    assert "image/svg" in favicon.headers["content-type"]
    assert "image/svg" in logo.headers["content-type"]


def test_product_identity_does_not_use_dashboard_naming() -> None:
    text = TestClient(create_app(runner_factory=_runner_factory)).get("/").text
    assert "SharipovAI — торговая система" in text
    assert "Dashboard" not in text


def test_russian_static_shell_has_no_common_english_navigation_labels() -> None:
    text = TestClient(create_app(runner_factory=_runner_factory)).get("/").text
    for label in (">Settings<", ">Portfolio<", ">Latest news<", ">Reports<"):
        assert label not in text


def test_runner_failure_does_not_crash_spa_or_api() -> None:
    client = TestClient(create_app(runner_factory=_failing_runner_factory))
    page = client.get("/")
    payload = client.get("/api/run").json()
    assert page.status_code == 200
    _assert_web2_shell(page.text)
    assert payload["decision"] == "WATCH"
    assert "Runner временно недоступен" in payload["report"]


def test_missing_runner_data_does_not_crash_spa_or_api() -> None:
    client = TestClient(create_app(runner_factory=_partial_runner_factory))
    page = client.get("/")
    payload = client.get("/api/run").json()
    assert page.status_code == 200
    _assert_web2_shell(page.text)
    assert payload["decision"] == "WATCH"
    assert payload["risk_level"] == "LOW"


def test_settings_and_self_analysis_are_current_spa_routes() -> None:
    client = TestClient(create_app(runner_factory=_runner_factory))
    for path in ("/settings", "/self-analysis"):
        response = client.get(path)
        assert response.status_code == 200
        _assert_web2_shell(response.text)
    assert 'data-page="settings"' in client.get("/settings").text
    assert 'data-page="learning"' in client.get("/self-analysis").text


def test_each_content_page_is_backed_by_one_nonempty_spa_shell() -> None:
    client = TestClient(create_app(runner_factory=_runner_factory))
    for path in ("/market", "/news", "/ai-decision", "/portfolio", "/paper-trading", "/learning", "/reports"):
        response = client.get(path)
        assert response.status_code == 200
        _assert_web2_shell(response.text)
        assert "Интерфейс готов" in response.text


def test_ai_control_center_keeps_existing_protected_panel_contract() -> None:
    response = TestClient(create_app(runner_factory=_runner_factory)).get("/ai-control-center")
    assert response.status_code == 200
    assert "AI Control Center" in response.text
    assert "Виртуальный кошелек" in response.text
    assert "Сохранить настройки" in response.text


def test_removed_crash_panel_is_replaced_by_risk_navigation() -> None:
    text = TestClient(create_app(runner_factory=_runner_factory)).get("/").text
    assert "Панель краш-теста" not in text
    assert 'data-page="risk"' in text
    assert "Центр рисков" in text


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
