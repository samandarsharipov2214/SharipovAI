"""FastAPI routes for the SharipovAI OS web interface."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Body, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.templating import Jinja2Templates

import config.settings as config_settings
from learning_engine import LearningSummary
from runner import RunnerOutput, SharipovAIRunner

from .i18n.loader import load_translations, normalize_language
from .models import CrashTestResult, DashboardView


router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


@router.get("/", response_class=HTMLResponse)
def home(request: Request) -> HTMLResponse:
    """Render the overview page."""

    view = _safe_view(request)
    return _render_page(request=request, page="overview", view=view)


@router.get("/market", response_class=HTMLResponse)
def market(request: Request) -> HTMLResponse:
    """Render the Market page."""

    return _render_page(request=request, page="market")


@router.get("/news", response_class=HTMLResponse)
def news(request: Request) -> HTMLResponse:
    """Render the News page."""

    return _render_page(request=request, page="news")


@router.get("/ai-decision", response_class=HTMLResponse)
def ai_decision(request: Request) -> HTMLResponse:
    """Render the AI Decision page."""

    view = _safe_view(request)
    return _render_page(request=request, page="ai-decision", view=view)


@router.get("/portfolio", response_class=HTMLResponse)
def portfolio(request: Request) -> HTMLResponse:
    """Render the Portfolio page."""

    view = _safe_view(request)
    return _render_page(request=request, page="portfolio", view=view)


@router.get("/paper-trading", response_class=HTMLResponse)
def paper_trading(request: Request) -> HTMLResponse:
    """Render the Paper Trading page."""

    view = _safe_view(request)
    return _render_page(request=request, page="paper-trading", view=view)


@router.get("/learning", response_class=HTMLResponse)
def learning(request: Request) -> HTMLResponse:
    """Render the Learning page."""

    view = _safe_view(request)
    return _render_page(request=request, page="learning", view=view)


@router.get("/self-analysis", response_class=HTMLResponse)
def self_analysis(request: Request) -> HTMLResponse:
    """Render the Self Analysis page."""

    return _render_page(request=request, page="self-analysis")


@router.get("/stress-lab", response_class=HTMLResponse)
def stress_lab(request: Request) -> HTMLResponse:
    """Render the Stress Lab page."""

    return _render_page(request=request, page="stress-lab")


@router.get("/ai-improvement", response_class=HTMLResponse)
def ai_improvement(request: Request) -> HTMLResponse:
    """Render the AI Improvement page."""

    return _render_page(request=request, page="ai-improvement")


@router.get("/reports", response_class=HTMLResponse)
def reports(request: Request) -> HTMLResponse:
    """Render the Reports page."""

    view = _safe_view(request)
    return _render_page(request=request, page="reports", view=view)


@router.get("/ai-control-center", response_class=HTMLResponse)
def ai_control_center(request: Request) -> HTMLResponse:
    """Render the AI Control Center page."""

    view = _safe_view(request)
    return _render_page(request=request, page="ai-control-center", view=view)


@router.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request) -> HTMLResponse:
    """Render the Settings page."""

    return _render_page(request=request, page="settings")


@router.get("/health")
def health() -> dict[str, str]:
    """Return health status."""

    return {"status": "ok"}


@router.get("/api/health")
def api_health() -> dict[str, str]:
    """Return API health status."""

    return {"status": "ok"}


@router.get("/api/run")
def api_run(request: Request) -> dict[str, object]:
    """Run the SharipovAI runner and return JSON output."""

    return _safe_view(request).to_dict()


@router.get("/api/translations/{lang}")
def translations(lang: str) -> dict[str, str]:
    """Return translations for a requested language."""

    return load_translations(lang)


@router.get("/api/crash-test")
def get_crash_test() -> dict[str, object]:
    """Return a deterministic default crash-test simulation."""

    return _evaluate_crash_test("market_drop").to_dict()


@router.post("/api/crash-test")
def post_crash_test(payload: dict[str, Any] | None = Body(default=None)) -> dict[str, object]:
    """Return a deterministic crash-test simulation for a requested scenario."""

    data = payload or {}
    scenario = str(data.get("scenario", "market_drop"))
    return _evaluate_crash_test(scenario).to_dict()


@router.get("/api/stress-lab/scenarios")
def stress_lab_scenarios() -> dict[str, object]:
    """Return deterministic Stress Lab scenario definitions."""

    return {"scenarios": _stress_scenarios()}


@router.post("/api/stress-lab/run")
def run_stress_lab(payload: dict[str, Any] | None = Body(default=None)) -> dict[str, object]:
    """Run a deterministic Stress Lab simulation."""

    return _evaluate_stress_lab(payload or {})


@router.get("/api/ai-improvement")
def ai_improvement_api() -> dict[str, object]:
    """Return deterministic AI improvement recommendations."""

    return {"recommendations": _improvement_recommendations()}


@router.get("/favicon.ico", include_in_schema=False)
def favicon() -> FileResponse:
    """Return favicon using SharipovAI OS branding."""

    return FileResponse(Path(__file__).parent / "static" / "favicon.svg")


@router.get("/logo.svg", include_in_schema=False)
def logo() -> FileResponse:
    """Return the SharipovAI OS logo."""

    return FileResponse(Path(__file__).parent / "static" / "logo.svg")


def _runner_factory(request: Request) -> Callable[[], SharipovAIRunner]:
    """Return the configured runner factory."""

    factory = getattr(request.app.state, "runner_factory", None)
    if callable(factory):
        return factory
    return SharipovAIRunner


def _render_page(
    *,
    request: Request,
    page: str,
    view: DashboardView | None = None,
) -> HTMLResponse:
    """Render a web interface page."""

    language = normalize_language(request.query_params.get("lang"))
    translations = load_translations(language)
    safe_view = view or _fallback_view()
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "page": page,
            "view": safe_view,
            "display": _display_values(safe_view, translations),
            "crash": _evaluate_crash_test("btc_drop_20"),
            "stress": _evaluate_stress_lab({"scenario": "btc_drop_20"}),
            "stress_scenarios": _stress_scenarios(),
            "improvements": _improvement_recommendations(),
            "settings": config_settings.settings,
            "nav_items": _nav_items(language),
            "lang": language,
            "t": translations,
        },
    )


def _nav_items(language: str) -> list[dict[str, str]]:
    """Return simplified primary navigation items."""

    return [
        {"key": "overview", "href": f"/?lang={language}", "page": "overview"},
        {"key": "ai_decision", "href": f"/ai-decision?lang={language}", "page": "ai-decision"},
        {"key": "portfolio", "href": f"/portfolio?lang={language}", "page": "portfolio"},
        {"key": "stress_lab", "href": f"/stress-lab?lang={language}", "page": "stress-lab"},
        {"key": "settings", "href": f"/settings?lang={language}", "page": "settings"},
    ]


def _view_from_output(output: RunnerOutput) -> DashboardView:
    """Convert runner output to dashboard view model."""

    return DashboardView(
        run_mode=config_settings.settings.run_mode,
        decision=str(getattr(output, "decision", "NO_DECISION")),
        confidence=float(getattr(output, "confidence", 0.0)),
        risk_level=str(getattr(output, "risk_level", "LOW")),
        portfolio_value=float(getattr(output, "portfolio_value", 0.0)),
        paper_cash=float(getattr(output, "paper_cash", 0.0)),
        paper_equity=float(getattr(output, "paper_equity", 0.0)),
        learning_summary=getattr(output, "learning_summary", _empty_learning_summary()),
        report=str(getattr(output, "report", "")),
        reason=str(getattr(output, "reason", "")),
        consensus=str(getattr(output, "consensus", "WEAK")),
        consensus_agreement=float(getattr(output, "consensus_agreement", 0.0)),
        paper_pnl=float(getattr(output, "paper_pnl", 0.0)),
        open_positions=int(getattr(output, "open_positions", 0)),
    )


def _safe_view(request: Request) -> DashboardView:
    """Run the configured runner and return a fallback view on failure."""

    try:
        output = _runner_factory(request)().run()
    except Exception:
        return _fallback_view()
    return _view_from_output(output)


def _fallback_view() -> DashboardView:
    """Return a safe fallback view when runner data is unavailable."""

    return DashboardView(
        run_mode=config_settings.settings.run_mode,
        decision="NO_DECISION",
        confidence=0.0,
        risk_level="LOW",
        portfolio_value=0.0,
        paper_cash=0.0,
        paper_equity=0.0,
        learning_summary=_empty_learning_summary(),
        report="",
        reason="",
        consensus="WEAK",
        consensus_agreement=0.0,
        paper_pnl=0.0,
        open_positions=0,
    )


def _empty_learning_summary() -> LearningSummary:
    """Return an empty learning summary."""

    return LearningSummary(
        total_trades=0,
        wins=0,
        losses=0,
        win_rate=0.0,
        average_profit=0.0,
        average_loss=0.0,
        best_trade=0.0,
        worst_trade=0.0,
        recommendations=[],
    )


def _display_values(view: DashboardView, translations: dict[str, str]) -> dict[str, str]:
    """Return translated display labels for dynamic values."""

    decision = _translate_enum(
        view.decision,
        {
            "BUY": "decision_buy_btc",
            "WATCH": "decision_watch",
            "IGNORE": "decision_ignore",
            "NO_DECISION": "decision_no_decision",
            "SELL": "decision_sell",
        },
        translations,
    )
    return {
        "decision": decision,
        "risk": _translate_enum(
            view.risk_level,
            {
                "LOW": "risk_low",
                "MEDIUM": "risk_medium",
                "HIGH": "risk_high",
                "CRITICAL": "risk_critical",
            },
            translations,
        ),
        "consensus": _translate_enum(
            view.consensus,
            {
                "UNANIMOUS": "consensus_unanimous",
                "STRONG": "consensus_strong",
                "MODERATE": "consensus_moderate",
                "WEAK": "consensus_weak",
                "CONFLICT": "consensus_conflict",
            },
            translations,
        ),
        "run_mode": _translate_enum(
            view.run_mode,
            {"DEMO": "demo", "LIVE": "live"},
            translations,
        ),
        "reason": translations["decision_reason_default"],
        "report": translations["runner_report_default"]
        if view.report
        else translations["runner_unavailable"],
    }


def _translate_enum(
    value: str,
    mapping: dict[str, str],
    translations: dict[str, str],
) -> str:
    """Translate an enum-like string value."""

    key = mapping.get(value.upper())
    if key is None:
        return value
    return translations[key]


def _evaluate_crash_test(scenario: str) -> CrashTestResult:
    """Evaluate a deterministic crash-test scenario."""

    normalized = scenario.strip().lower().replace("-", "_")
    losses = {
        "system_crash": 0.0,
        "market_drop": 7.5,
        "btc_drop_10": 10.0,
        "btc_drop_20": 20.0,
        "market_crash_50": 50.0,
        "virtual_capital_loss_10": 10.0,
        "custom_scenario": 5.0,
    }
    loss_percent = losses.get(normalized, losses["market_drop"])
    capital_before = 10_000.0
    loss_amount = capital_before * loss_percent / 100
    capital_after = capital_before - loss_amount
    measures = [
        "reduce risk per trade",
        "block new BUY decisions",
        "switch to WATCH mode",
        "reduce high-risk paper positions",
        "notify user",
        "increase monitoring",
        "recommend safer settings",
    ]
    reaction = "Switch to protective mode and prevent new risk expansion."
    result = "Simulation completed safely. No real trading actions were executed."
    return CrashTestResult(
        scenario=normalized,
        capital_before=capital_before,
        capital_after=capital_after,
        loss_amount=loss_amount,
        loss_percent=loss_percent,
        ai_reaction=reaction,
        protective_measures=measures,
        result=result,
    )


def _stress_scenarios() -> list[dict[str, str]]:
    """Return deterministic Stress Lab scenarios."""

    return [
        {"id": "btc_drop_10", "label": "BTC price drop 10%"},
        {"id": "btc_drop_20", "label": "BTC price drop 20%"},
        {"id": "market_crash_50", "label": "Market crash 50%"},
        {"id": "virtual_capital_loss_10", "label": "Virtual capital loss 10%"},
        {"id": "liquidity_shock", "label": "Liquidity shock"},
        {"id": "news_panic", "label": "News panic"},
        {"id": "exchange_outage", "label": "Exchange outage"},
        {"id": "custom_scenario", "label": "Custom scenario"},
    ]


def _evaluate_stress_lab(payload: dict[str, Any]) -> dict[str, object]:
    """Evaluate a deterministic Stress Lab simulation."""

    scenario = str(payload.get("scenario", "btc_drop_20")).strip().lower().replace("-", "_")
    starting_capital = _safe_float(payload.get("starting_virtual_capital"), 10_000.0)
    cash_before = _safe_float(payload.get("cash_before"), starting_capital * 0.72)
    exposure_before = _safe_float(payload.get("current_exposure"), 28.0)
    max_drawdown = _safe_float(payload.get("maximum_acceptable_drawdown"), 10.0)
    price_drop_percent = _scenario_loss_percent(scenario, payload)
    capital_loss_percent = _safe_float(payload.get("capital_loss_percent"), price_drop_percent)
    liquidity_reduction_percent = _safe_float(payload.get("liquidity_reduction_percent"), 35.0)
    volatility_spike_percent = _safe_float(payload.get("volatility_spike_percent"), price_drop_percent * 1.6)
    unrealized_loss = starting_capital * min(price_drop_percent, 100.0) / 100 * exposure_before / 100
    realized_loss = starting_capital * min(capital_loss_percent, 100.0) / 100 * 0.25
    loss_amount = unrealized_loss + realized_loss
    capital_after = max(starting_capital - loss_amount, 0.0)
    cash_after = max(cash_before - realized_loss, 0.0)
    equity_after = capital_after
    loss_percent = 0.0 if starting_capital <= 0 else loss_amount / starting_capital * 100
    new_exposure = max(exposure_before - min(price_drop_percent, 50.0) * 0.25, 0.0)
    new_risk_level = _risk_level_from_loss(loss_percent, max_drawdown)
    classification = _classification_from_loss(loss_percent, max_drawdown)
    protection_triggered = loss_percent >= max_drawdown
    return {
        "scenario": scenario,
        "parameters": {
            "asset_symbol": str(payload.get("asset_symbol", "BTCUSDT")),
            "price_drop_percent": price_drop_percent,
            "capital_loss_percent": capital_loss_percent,
            "liquidity_reduction_percent": liquidity_reduction_percent,
            "volatility_spike_percent": volatility_spike_percent,
            "news_sentiment_shock": str(payload.get("news_sentiment_shock", "negative")),
            "duration": str(payload.get("duration", "4h")),
            "starting_virtual_capital": starting_capital,
            "current_exposure": exposure_before,
            "maximum_acceptable_drawdown": max_drawdown,
        },
        "before": {
            "capital": starting_capital,
            "cash": cash_before,
            "equity": starting_capital,
            "positions": 2,
            "risk": "MEDIUM" if exposure_before >= 25 else "LOW",
            "exposure": exposure_before,
        },
        "after": {
            "capital": capital_after,
            "cash": cash_after,
            "equity": equity_after,
            "unrealized_loss": unrealized_loss,
            "realized_loss": realized_loss,
            "loss_amount": loss_amount,
            "loss_percent": loss_percent,
            "new_risk_level": new_risk_level,
            "new_exposure": new_exposure,
        },
        "ai_reaction": [
            "switch to WATCH mode",
            "block new BUY decisions",
            "reduce risk per trade",
            "reduce position size",
            "close or reduce high-risk positions in Paper Trading",
            "increase monitoring frequency",
            "notify user",
            "recommend safer settings",
            "pause trading if drawdown limit exceeded" if protection_triggered else "continue controlled monitoring",
        ],
        "protective_measures": [
            "risk limit applied",
            "BUY signals blocked",
            "drawdown checked",
            "portfolio exposure reduced",
            "user notification prepared",
            "learning record created",
            "self-analysis report updated",
        ],
        "classification": classification,
        "charts": {
            "capital_before_after": [starting_capital, capital_after],
            "loss_waterfall": [unrealized_loss, realized_loss, loss_amount],
            "crash_dynamics": [starting_capital, starting_capital - unrealized_loss, capital_after],
            "risk_level_change": [
                _risk_score_from_level("MEDIUM" if exposure_before >= 25 else "LOW"),
                _risk_score_from_level(new_risk_level),
            ],
        },
    }


def _safe_float(value: Any, default: float) -> float:
    """Convert a value to float with a safe default."""

    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return max(parsed, 0.0)


def _scenario_loss_percent(scenario: str, payload: dict[str, Any]) -> float:
    """Resolve the deterministic loss percent for a scenario."""

    mapping = {
        "btc_drop_10": 10.0,
        "btc_drop_20": 20.0,
        "market_crash_50": 50.0,
        "virtual_capital_loss_10": 10.0,
        "liquidity_shock": 18.0,
        "news_panic": 14.0,
        "exchange_outage": 22.0,
        "custom_scenario": _safe_float(payload.get("price_drop_percent"), 12.0),
    }
    return mapping.get(scenario, 20.0)


def _risk_level_from_loss(loss_percent: float, max_drawdown: float) -> str:
    """Return a deterministic risk level from simulated loss."""

    if loss_percent >= max_drawdown:
        return "CRITICAL"
    if loss_percent >= max_drawdown * 0.7:
        return "HIGH"
    if loss_percent >= max_drawdown * 0.35:
        return "MEDIUM"
    return "LOW"


def _classification_from_loss(loss_percent: float, max_drawdown: float) -> str:
    """Return deterministic Stress Lab classification."""

    if loss_percent >= max_drawdown:
        return "capital protection triggered"
    if loss_percent >= max_drawdown * 0.75:
        return "critical"
    if loss_percent >= max_drawdown * 0.35:
        return "warning"
    return "system stable"


def _risk_score_from_level(level: str) -> int:
    """Map risk level to chart score."""

    return {"LOW": 20, "MEDIUM": 50, "HIGH": 75, "CRITICAL": 95}.get(level, 20)


def _improvement_recommendations() -> list[dict[str, object]]:
    """Return deterministic AI Improvement recommendations."""

    return [
        {
            "title": "Add Macro Agent",
            "priority": "HIGH",
            "expected_benefit": "Better CPI, rates, and central bank awareness.",
            "difficulty": "MEDIUM",
            "affected_modules": ["agents", "data_layer", "ai_core"],
            "reason": "Connects weak market analysis and missed opportunities to macro conditions.",
            "status": "recommended",
        },
        {
            "title": "Add Sentiment Agent",
            "priority": "HIGH",
            "expected_benefit": "Earlier detection of news panic and false signals.",
            "difficulty": "MEDIUM",
            "affected_modules": ["news_agent", "consensus", "confidence"],
            "reason": "Links weak news analysis, false signals, and agent conflicts.",
            "status": "recommended",
        },
        {
            "title": "Add On-chain Agent",
            "priority": "MEDIUM",
            "expected_benefit": "Whale flow and exchange movement context.",
            "difficulty": "HIGH",
            "affected_modules": ["agents", "data_layer", "risk_engine"],
            "reason": "Improves missed opportunity review and high drawdown diagnostics.",
            "status": "planned",
        },
        {
            "title": "Add Fear & Greed Agent",
            "priority": "MEDIUM",
            "expected_benefit": "More stable sentiment regime detection.",
            "difficulty": "LOW",
            "affected_modules": ["agents", "confidence"],
            "reason": "Reduces weak market analysis during extreme sentiment.",
            "status": "recommended",
        },
        {
            "title": "Improve News Agent with source credibility",
            "priority": "HIGH",
            "expected_benefit": "Lower false signal rate.",
            "difficulty": "MEDIUM",
            "affected_modules": ["news_agent", "learning_engine"],
            "reason": "Connects false signals and weak news analysis to source quality.",
            "status": "recommended",
        },
        {
            "title": "Improve Risk Engine with VaR",
            "priority": "HIGH",
            "expected_benefit": "Better capital protection during drawdowns.",
            "difficulty": "HIGH",
            "affected_modules": ["risk_engine", "portfolio_engine"],
            "reason": "Directly addresses high drawdown and wrong trade diagnostics.",
            "status": "recommended",
        },
        {
            "title": "Improve Learning Engine with strategy comparison",
            "priority": "MEDIUM",
            "expected_benefit": "Better feedback from wrong trades and poor win rate.",
            "difficulty": "MEDIUM",
            "affected_modules": ["learning_engine", "memory"],
            "reason": "Connects poor win rate with repeatable improvement review.",
            "status": "planned",
        },
        {
            "title": "Add Telegram Bot",
            "priority": "MEDIUM",
            "expected_benefit": "Faster user notification and approvals.",
            "difficulty": "MEDIUM",
            "affected_modules": ["runner", "dashboard"],
            "reason": "Improves user approval workflow and alerts.",
            "status": "planned",
        },
        {
            "title": "Add iOS App",
            "priority": "LOW",
            "expected_benefit": "Mobile access to decisions and reports.",
            "difficulty": "HIGH",
            "affected_modules": ["api", "dashboard"],
            "reason": "Supports future mobile ecosystem.",
            "status": "future",
        },
    ]
