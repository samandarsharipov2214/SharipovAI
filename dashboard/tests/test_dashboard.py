"""Tests for the FastAPI SharipovAI OS web interface."""

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


def test_app_creates_successfully() -> None:
    """FastAPI app is created successfully."""

    app = create_app(runner_factory=_runner_factory)

    assert app.title == "SharipovAI OS"


def test_all_pages_return_success() -> None:
    """All visible pages return HTTP 200 and render the OS shell."""

    client = TestClient(create_app(runner_factory=_runner_factory))

    for path in VISIBLE_PAGES:
        response = client.get(path)
        assert response.status_code == 200
        assert "SharipovAI OS" in response.text
        assert "os-sidebar" in response.text
        assert "os-main" in response.text


def test_overview_page_renders_rebuilt_live_interface() -> None:
    """Overview page matches the rebuilt index.html structure."""

    response = TestClient(create_app(runner_factory=_runner_factory)).get("/?lang=ru")

    assert response.status_code == 200
    assert "hero-decision" in response.text
    assert "id=\"hero-decision\"" in response.text
    assert "id=\"hero-confidence\"" in response.text
    assert "id=\"portfolio-equity\"" in response.text
    assert "id=\"run-analysis\"" in response.text
    assert "Стресс-лаборатория" in response.text


def test_overview_page_displays_runner_values() -> None:
    """Overview page includes translated runner output values."""

    response = TestClient(create_app(runner_factory=_runner_factory)).get("/?lang=en")

    assert response.status_code == 200
    assert "BUY BITCOIN" in response.text
    assert "LOW" in response.text
    assert "UNANIMOUS 100.0%" in response.text
    assert "10000.00 USDT" in response.text
    assert "9500.00 USDT" in response.text


def test_health_endpoints_work() -> None:
    """Health endpoints return ok."""

    client = TestClient(create_app(runner_factory=_runner_factory))

    assert client.get("/health").json() == {"status": "ok"}
    assert client.get("/api/health").json() == {"status": "ok"}


def test_api_run_endpoint_works() -> None:
    """API run endpoint returns JSON runner output."""

    response = TestClient(create_app(runner_factory=_runner_factory)).get("/api/run")

    assert response.status_code == 200
    payload = response.json()
    assert payload["decision"] == "BUY"
    assert payload["risk_level"] == "LOW"
    assert payload["paper_cash"] == 9500.0
    assert payload["paper_equity"] == 10000.0
    assert payload["learning_summary"]["total_trades"] == 1


def test_translation_endpoint_works() -> None:
    """Translation endpoint returns requested translation JSON."""

    response = TestClient(create_app(runner_factory=_runner_factory)).get(
        "/api/translations/en"
    )

    assert response.status_code == 200
    assert response.json()["overview"] == "Overview"


def test_crash_test_endpoints_work() -> None:
    """Crash-test endpoints return deterministic safe simulation output."""

    client = TestClient(create_app(runner_factory=_runner_factory))

    get_response = client.get("/api/crash-test")
    post_response = client.post("/api/crash-test", json={"scenario": "market_crash_50"})

    assert get_response.status_code == 200
    assert post_response.status_code == 200
    payload = post_response.json()
    assert payload["scenario"] == "market_crash_50"
    assert payload["loss_percent"] == 50.0
    assert "block new BUY decisions" in payload["protective_measures"]


def test_stress_lab_page_returns_success_and_matches_rebuilt_template() -> None:
    """Stress Lab page renders the rebuilt stress interface."""

    response = TestClient(create_app(runner_factory=_runner_factory)).get(
        "/stress-lab?lang=en"
    )

    assert response.status_code == 200
    assert "STRESS LAB" in response.text
    assert "data-stress-scenario=\"btc_drop_20\"" in response.text
    assert "id=\"stress-scenario\"" in response.text
    assert "id=\"stress-before\"" in response.text
    assert "id=\"stress-after\"" in response.text
    assert "id=\"stress-measures\"" in response.text


def test_stress_lab_scenario_list_api_works() -> None:
    """Stress Lab scenario list API returns deterministic scenarios."""

    response = TestClient(create_app(runner_factory=_runner_factory)).get(
        "/api/stress-lab/scenarios"
    )

    assert response.status_code == 200
    scenarios = response.json()["scenarios"]
    assert {"id": "btc_drop_20", "label": "BTC price drop 20%"} in scenarios
    assert {"id": "market_crash_50", "label": "Market crash 50%"} in scenarios
    assert {"id": "virtual_capital_loss_10", "label": "Virtual capital loss 10%"} in scenarios


def test_stress_lab_btc_drop_20_scenario_works() -> None:
    """BTC drop 20 scenario returns loss data and protective actions."""

    response = TestClient(create_app(runner_factory=_runner_factory)).post(
        "/api/stress-lab/run",
        json={"scenario": "btc_drop_20"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["scenario"] == "btc_drop_20"
    assert payload["parameters"]["price_drop_percent"] == 20.0
    assert payload["after"]["loss_percent"] >= 0
    assert "switch to WATCH mode" in payload["ai_reaction"]
    assert "risk limit applied" in payload["protective_measures"]
    assert "capital" in payload["before"]
    assert "capital" in payload["after"]


def test_stress_lab_market_crash_50_scenario_works() -> None:
    """Market crash 50 scenario returns critical simulation data."""

    response = TestClient(create_app(runner_factory=_runner_factory)).post(
        "/api/stress-lab/run",
        json={"scenario": "market_crash_50"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["scenario"] == "market_crash_50"
    assert payload["parameters"]["price_drop_percent"] == 50.0
    assert payload["after"]["loss_amount"] > 0


def test_stress_lab_virtual_capital_loss_scenario_works() -> None:
    """Virtual capital loss scenario returns deterministic result."""

    response = TestClient(create_app(runner_factory=_runner_factory)).post(
        "/api/stress-lab/run",
        json={"scenario": "virtual_capital_loss_10"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["scenario"] == "virtual_capital_loss_10"
    assert payload["parameters"]["capital_loss_percent"] == 10.0


def test_stress_lab_critical_drawdown_triggers_protection() -> None:
    """Critical drawdown triggers capital protection classification."""

    response = TestClient(create_app(runner_factory=_runner_factory)).post(
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


def test_stress_lab_translations_work() -> None:
    """Stress Lab navigation labels are translated."""

    client = TestClient(create_app(runner_factory=_runner_factory))

    ru = client.get("/stress-lab?lang=ru")
    en = client.get("/stress-lab?lang=en")
    uz = client.get("/stress-lab?lang=uz")

    assert "Стресс-лаборатория" in ru.text
    assert "Stress Lab" in en.text
    assert "Stress laboratoriyasi" in uz.text


def test_ai_improvement_page_and_api_work() -> None:
    """AI Improvement page and API expose recommendations."""

    client = TestClient(create_app(runner_factory=_runner_factory))

    page = client.get("/ai-improvement?lang=en")
    api = client.get("/api/ai-improvement")

    assert page.status_code == 200
    assert "AI Improvement" in page.text
    assert "Улучшение AI" in page.text
    assert "Macro Agent" in page.text
    assert api.status_code == 200
    assert api.json()["recommendations"][0]["title"] == "Add Macro Agent"


def test_ai_improvement_russian_label_works() -> None:
    """AI Improvement page has Russian labels."""

    response = TestClient(create_app(runner_factory=_runner_factory)).get(
        "/ai-improvement?lang=ru"
    )

    assert response.status_code == 200
    assert "Улучшение AI" in response.text


def test_logo_and_favicon_routes_work() -> None:
    """Logo and favicon routes return SVG branding."""

    client = TestClient(create_app(runner_factory=_runner_factory))

    favicon = client.get("/favicon.ico")
    logo = client.get("/logo.svg")

    assert favicon.status_code == 200
    assert logo.status_code == 200
    assert "image/svg" in favicon.headers["content-type"]
    assert "image/svg" in logo.headers["content-type"]


def test_russian_translation_is_complete_for_core_labels() -> None:
    """Russian UI appears when lang is ru."""

    response = TestClient(create_app(runner_factory=_runner_factory)).get("/?lang=ru")

    assert response.status_code == 200
    assert "Обзор" in response.text
    assert "Умнее. Данные. Решения." in response.text
    assert "ПОКУПАТЬ БИТКОЙН" in response.text
    assert "НИЗКИЙ" in response.text
    assert "ЕДИНОГЛАСНО" in response.text


def test_english_translation_appears() -> None:
    """English UI appears when lang is en."""

    response = TestClient(create_app(runner_factory=_runner_factory)).get("/?lang=en")

    assert response.status_code == 200
    assert "Overview" in response.text
    assert "Smarter. Data. Decisions." in response.text
    assert "BUY BITCOIN" in response.text


def test_uzbek_translation_appears() -> None:
    """Uzbek UI appears when lang is uz."""

    response = TestClient(create_app(runner_factory=_runner_factory)).get("/?lang=uz")

    assert response.status_code == 200
    assert "Umumiy ko&#39;rinish" in response.text
    assert "Aqlliroq. Ma&#39;lumot. Qarorlar." in response.text
    assert "BITCOIN SOTIB OLISH" in response.text


def test_invalid_language_falls_back_to_russian() -> None:
    """Invalid language falls back to Russian."""

    response = TestClient(create_app(runner_factory=_runner_factory)).get("/?lang=de")

    assert response.status_code == 200
    assert "Обзор" in response.text


def test_no_visible_dashboard_product_naming_remains() -> None:
    """Visible product identity does not use Dashboard naming."""

    response = TestClient(create_app(runner_factory=_runner_factory)).get("/?lang=en")

    assert response.status_code == 200
    assert "Dashboard" not in response.text


def test_russian_ui_does_not_contain_common_english_labels() -> None:
    """Russian UI does not expose common English navigation labels."""

    response = TestClient(create_app(runner_factory=_runner_factory)).get("/?lang=ru")

    assert response.status_code == 200
    for label in ("Dashboard", "Settings", "Portfolio", "Latest news", "Reports"):
        assert label not in response.text


def test_runner_failure_does_not_crash_overview_page() -> None:
    """Runner failures render a safe fallback state."""

    response = TestClient(create_app(runner_factory=_failing_runner_factory)).get("/")

    assert response.status_code == 200
    assert "SharipovAI OS" in response.text
    assert "НЕТ РЕШЕНИЯ" in response.text
    assert "Runner временно недоступен" in response.text


def test_missing_runner_data_does_not_crash_overview_page() -> None:
    """Incomplete runner output renders without crashing."""

    response = TestClient(create_app(runner_factory=_partial_runner_factory)).get("/")

    assert response.status_code == 200
    assert "SharipovAI OS" in response.text
    assert "id=\"hero-decision\"" in response.text


def test_settings_page_renders_rebuilt_control_sections() -> None:
    """Settings page contains the rebuilt control-center structure."""

    response = TestClient(create_app(runner_factory=_runner_factory)).get("/settings")

    assert response.status_code == 200
    for label in (
        "Настройки",
        "Виртуальный кошелек",
        "Риск",
        "Лимиты",
        "Безопасность",
        "Реальная торговля выключена",
    ):
        assert label in response.text


def test_self_analysis_page_renders_recommendations_section() -> None:
    """Self Analysis page shows recommendations and safety messaging."""

    response = TestClient(create_app(runner_factory=_runner_factory)).get("/self-analysis")

    assert response.status_code == 200
    assert "Самоанализ ошибок" in response.text
    assert "Рекомендации" in response.text
    assert "AI не меняет себя автоматически" in response.text


def test_each_content_page_is_not_empty() -> None:
    """Every fallback content page includes meaningful rebuilt section text."""

    client = TestClient(create_app(runner_factory=_runner_factory))

    for path in (
        "/market",
        "/news",
        "/ai-decision",
        "/portfolio",
        "/paper-trading",
        "/learning",
        "/reports",
    ):
        response = client.get(path)
        assert response.status_code == 200
        assert "Раздел активен" in response.text
        assert "Страница подключена к SharipovAI OS" in response.text
        assert "metric-grid" in response.text


def test_ai_control_center_uses_rebuilt_settings_panel() -> None:
    """AI Control Center shares the rebuilt control panel."""

    response = TestClient(create_app(runner_factory=_runner_factory)).get(
        "/ai-control-center"
    )

    assert response.status_code == 200
    assert "AI Control Center" in response.text
    assert "Виртуальный кошелек" in response.text
    assert "Сохранить настройки" in response.text


def test_crash_test_panel_was_replaced_by_stress_lab_link() -> None:
    """Overview links to Stress Lab instead of the removed crash-test card."""

    response = TestClient(create_app(runner_factory=_runner_factory)).get("/")

    assert response.status_code == 200
    assert "Панель краш-теста" not in response.text
    assert "href=\"/stress-lab?lang=ru\"" in response.text
    assert "Стресс-лаборатория" in response.text


class _FakeRunner:
    """Fake runner for web tests."""

    def run(self) -> RunnerOutput:
        """Return deterministic runner output."""

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
    """Runner that raises to test fallback rendering."""

    def run(self) -> RunnerOutput:
        """Raise a deterministic runtime error."""

        raise RuntimeError("runner unavailable")


class _PartialRunner:
    """Runner that returns incomplete data."""

    def run(self) -> object:
        """Return an object missing most RunnerOutput attributes."""

        return object()


def _runner_factory() -> _FakeRunner:
    """Return a fake runner."""

    return _FakeRunner()


def _failing_runner_factory() -> _FailingRunner:
    """Return a failing runner."""

    return _FailingRunner()


def _partial_runner_factory() -> _PartialRunner:
    """Return a partial runner."""

    return _PartialRunner()
