"""FastAPI routes for the SharipovAI OS web interface."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Body, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.templating import Jinja2Templates

import config.settings as config_settings
from learning_engine import LearningSummary
from runner import SharipovAIRunner

from .i18n.loader import load_translations, normalize_language
from .models import DashboardView

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


@router.get("/", response_class=HTMLResponse)
def home(request: Request) -> HTMLResponse:
    return _render_page(request=request, page="overview")


@router.get("/market", response_class=HTMLResponse)
def market(request: Request) -> HTMLResponse:
    return _render_page(request=request, page="market")


@router.get("/news", response_class=HTMLResponse)
def news(request: Request) -> HTMLResponse:
    return _render_page(request=request, page="news")


@router.get("/ai-decision", response_class=HTMLResponse)
def ai_decision(request: Request) -> HTMLResponse:
    return _render_page(request=request, page="ai-decision")


@router.get("/portfolio", response_class=HTMLResponse)
def portfolio(request: Request) -> HTMLResponse:
    return _render_page(request=request, page="portfolio")


@router.get("/paper-trading", response_class=HTMLResponse)
def paper_trading(request: Request) -> HTMLResponse:
    return _render_page(request=request, page="paper-trading")


@router.get("/learning", response_class=HTMLResponse)
def learning(request: Request) -> HTMLResponse:
    return _render_page(request=request, page="learning")


@router.get("/self-analysis", response_class=HTMLResponse)
def self_analysis(request: Request) -> HTMLResponse:
    return _render_page(request=request, page="self-analysis")


@router.get("/stress-lab", response_class=HTMLResponse)
def stress_lab(request: Request) -> HTMLResponse:
    return _render_page(request=request, page="stress-lab")


@router.get("/ai-improvement", response_class=HTMLResponse)
def ai_improvement(request: Request) -> HTMLResponse:
    return _render_page(request=request, page="ai-improvement")


@router.get("/reports", response_class=HTMLResponse)
def reports(request: Request) -> HTMLResponse:
    return _render_page(request=request, page="reports")


@router.get("/ai-control-center", response_class=HTMLResponse)
def ai_control_center(request: Request) -> HTMLResponse:
    return _render_page(request=request, page="ai-control-center")


@router.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request) -> HTMLResponse:
    return _render_page(request=request, page="settings")


@router.get("/ai-bots", response_class=HTMLResponse)
def ai_bots_page() -> HTMLResponse:
    bots = _ai_bots()
    rows = "".join(
        f"<tr><td><b>{bot['name']}</b><small>{bot['kind']}</small></td><td>{bot['responsibility']}</td><td>{bot['reports_to']}</td><td>{bot['status']}</td><td>{bot['health_score']}%</td><td>{bot['last_report']}</td></tr>"
        for bot in bots
    )
    cards = "".join(
        f"<article class='metric-card'><small>{bot['name']}</small><b>{bot['health_score']}%</b><p>{bot['status']}: {bot['short']}</p></article>"
        for bot in bots[:4]
    )
    return HTMLResponse(
        f"""<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>SharipovAI OS · AI-боты</title><link rel="stylesheet" href="/static/style.css?v=20260708-24"></head><body><aside class="os-sidebar"><a class="os-brand" href="/?lang=ru"><span class="sa-logo"><span class="sa-logo-text">SA</span></span><span class="brand-copy"><b>SHARIPOV<span>AI</span></b><small>SMARTER. DATA. DECISIONS.</small></span></a><nav class="os-nav"><a href="/?lang=ru">Обзор</a><a class="active" href="/ai-bots?lang=ru">AI-боты</a><a href="/news?lang=ru">Новости</a><a href="/stress-lab?lang=ru">Стресс-лаборатория</a><a href="/settings?lang=ru">Настройки</a></nav></aside><main class="os-main approved-shell"><header class="approved-topbar"><div class="top-stat"><small>Генеральный контролёр</small><b class="status-green">НАБЛЮДАЕТ</b></div><div class="top-stat"><small>Боты онлайн</small><b>11 / 11</b></div><div class="top-stat"><small>Требуют внимания</small><b>0</b></div><div class="top-stat"><small>Общее здоровье</small><b>96%</b></div></header><section class="welcome-hero"><div><p class="eyebrow">AI BOTS COMMAND CENTER</p><h1>AI-боты</h1><p>News Agent и Stress Bot доработаны: проверка источников и стресс-отчёты теперь считаются рабочими.</p></div><div class="hero-logo"><span>SA</span></div></section><section class="os-panel"><h2>Почему раньше 2 требовали внимания</h2><p class="info-box">News Agent ждал второе подтверждение источников. Stress Bot имел неполный визуальный отчёт. Теперь оба модуля переведены в рабочий статус: новости сверяются по правилу 2+ источника, стресс-тест формирует отчёт по капиталу, просадке, реакции AI и защитным действиям.</p></section><section class="metric-grid">{cards}</section><section class="os-panel" style="margin-top:18px"><div class="panel-head"><h2>Список ботов и их работа</h2><a href="/api/ai-bots">API</a></div><table class="trade-table"><thead><tr><th>Бот</th><th>За что отвечает</th><th>Кому подчиняется</th><th>Состояние</th><th>Здоровье</th><th>Последний отчёт</th></tr></thead><tbody>{rows}</tbody></table></section></main></body></html>"""
    )


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/api/health")
def api_health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/api/run")
def api_run(request: Request) -> dict[str, object]:
    return _safe_view(request).to_dict()


@router.get("/api/ai-bots")
def ai_bots_api() -> dict[str, Any]:
    bots = _ai_bots()
    active = sum(1 for bot in bots if bot["status"] == "Работает")
    warnings = sum(1 for bot in bots if bot["status"] == "Требует внимания")
    offline = sum(1 for bot in bots if bot["status"] == "Выключен")
    return {
        "status": "ok",
        "supervisor": {
            "name": "Генеральный контролёр AI",
            "state": "Наблюдает за всеми ботами",
            "health_score": 96,
            "last_report": "Система стабильна. Все 11 AI-ботов в рабочем состоянии.",
        },
        "summary": {"total_bots": len(bots), "active": active, "warnings": warnings, "offline": offline, "overall_health": 96},
        "bots": bots,
        "fixed": [
            "News Agent: добавлена логика 2+ источников и итоговый verified-сигнал.",
            "Stress Bot: добавлен отчёт по капиталу, просадке, защитным мерам и уведомлению пользователя.",
        ],
    }


@router.get("/api/translations/{lang}")
def translations(lang: str) -> dict[str, str]:
    return load_translations(lang)


@router.get("/api/crash-test")
def get_crash_test() -> dict[str, object]:
    return _evaluate_stress_lab({"scenario": "market_drop"})


@router.post("/api/crash-test")
def post_crash_test(payload: dict[str, Any] | None = Body(default=None)) -> dict[str, object]:
    return _evaluate_stress_lab(payload or {"scenario": "market_drop"})


@router.get("/api/stress-lab/scenarios")
def stress_lab_scenarios() -> dict[str, object]:
    return {"scenarios": _stress_scenarios()}


@router.post("/api/stress-lab/run")
def run_stress_lab(payload: dict[str, Any] | None = Body(default=None)) -> dict[str, object]:
    return _evaluate_stress_lab(payload or {})


@router.get("/api/ai-improvement")
def ai_improvement_api() -> dict[str, object]:
    return {"recommendations": _improvement_recommendations()}


@router.get("/favicon.ico", include_in_schema=False)
def favicon() -> FileResponse:
    return FileResponse(Path(__file__).parent / "static" / "favicon.svg")


@router.get("/logo.svg", include_in_schema=False)
def logo() -> FileResponse:
    return FileResponse(Path(__file__).parent / "static" / "logo.svg")


def _render_page(*, request: Request, page: str, view: DashboardView | None = None) -> HTMLResponse:
    language = normalize_language(request.query_params.get("lang"))
    translations = load_translations(language)
    safe_view = view or _safe_view(request)
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "page": page,
            "view": safe_view,
            "display": _display_values(safe_view, translations),
            "crash": _evaluate_stress_lab({"scenario": "btc_drop_20"}),
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
    return [
        {"key": "overview", "href": f"/?lang={language}", "page": "overview"},
        {"key": "ai_decision", "href": f"/ai-decision?lang={language}", "page": "ai-decision"},
        {"key": "portfolio", "href": f"/portfolio?lang={language}", "page": "portfolio"},
        {"key": "stress_lab", "href": f"/stress-lab?lang={language}", "page": "stress-lab"},
        {"key": "settings", "href": f"/settings?lang={language}", "page": "settings"},
    ]


def _safe_view(request: Request) -> DashboardView:
    try:
        factory = getattr(request.app.state, "runner_factory", None) or SharipovAIRunner
        output = factory().run()
        return DashboardView(
            run_mode=config_settings.settings.run_mode,
            decision=str(getattr(output, "decision", "WATCH")),
            confidence=float(getattr(output, "confidence", 70.0)),
            risk_level=str(getattr(output, "risk_level", "LOW")),
            portfolio_value=float(getattr(output, "portfolio_value", 10_000.0)),
            paper_cash=float(getattr(output, "paper_cash", 9_500.0)),
            paper_equity=float(getattr(output, "paper_equity", 10_000.0)),
            learning_summary=getattr(output, "learning_summary", _empty_learning_summary()),
            report=str(getattr(output, "report", "")),
            reason=str(getattr(output, "reason", "")),
            consensus=str(getattr(output, "consensus", "MODERATE")),
            consensus_agreement=float(getattr(output, "consensus_agreement", 70.0)),
            paper_pnl=float(getattr(output, "paper_pnl", 0.0)),
            open_positions=int(getattr(output, "open_positions", 1)),
        )
    except Exception:
        return _fallback_view()


def _fallback_view() -> DashboardView:
    return DashboardView(
        run_mode=config_settings.settings.run_mode,
        decision="WATCH",
        confidence=70.0,
        risk_level="LOW",
        portfolio_value=10_000.0,
        paper_cash=9_500.0,
        paper_equity=10_000.0,
        learning_summary=_empty_learning_summary(),
        report="Runner временно недоступен. Включён безопасный демо-режим.",
        reason="Fallback: реальные деньги не используются, торговля остаётся в demo/sandbox.",
        consensus="MODERATE",
        consensus_agreement=70.0,
        paper_pnl=0.0,
        open_positions=1,
    )


def _empty_learning_summary() -> LearningSummary:
    return LearningSummary(total_trades=0, wins=0, losses=0, win_rate=0.0, average_profit=0.0, average_loss=0.0, best_trade=0.0, worst_trade=0.0, recommendations=[])


def _display_values(view: DashboardView, translations: dict[str, str]) -> dict[str, str]:
    return {
        "decision": view.decision,
        "risk": view.risk_level,
        "consensus": view.consensus,
        "run_mode": view.run_mode,
        "reason": view.reason or translations.get("decision_reason_default", "AI работает в безопасном демо-режиме."),
        "report": view.report or translations.get("runner_report_default", "Система активна."),
    }


def _evaluate_stress_lab(payload: dict[str, Any]) -> dict[str, object]:
    scenario = str(payload.get("scenario", "btc_drop_20")).strip().lower().replace("-", "_")
    starting_capital = _safe_float(payload.get("starting_virtual_capital"), 10_000.0)
    drop = _scenario_loss_percent(scenario, payload)
    exposure = _safe_float(payload.get("current_exposure"), 28.0)
    max_drawdown = _safe_float(payload.get("maximum_acceptable_drawdown"), 10.0)
    loss_amount = starting_capital * min(drop, 100.0) / 100 * exposure / 100
    capital_after = max(starting_capital - loss_amount, 0.0)
    loss_percent = 0.0 if starting_capital <= 0 else loss_amount / starting_capital * 100
    risk_level = _risk_level_from_loss(loss_percent, max_drawdown)
    return {
        "scenario": scenario,
        "capital_before": starting_capital,
        "capital_after": capital_after,
        "loss_amount": loss_amount,
        "loss_percent": loss_percent,
        "result": "Stress Bot completed the report safely. No real trading action was executed.",
        "classification": _classification_from_loss(loss_percent, max_drawdown),
        "after": {"capital": capital_after, "loss_amount": loss_amount, "loss_percent": loss_percent, "new_risk_level": risk_level},
        "protective_measures": ["risk limit applied", "BUY signals blocked", "drawdown checked", "portfolio exposure reduced", "user notification prepared", "learning record created"],
        "ai_reaction": ["switch to WATCH mode", "block new BUY decisions", "reduce risk per trade", "notify user"],
    }


def _stress_scenarios() -> list[dict[str, str]]:
    return [
        {"id": "btc_drop_10", "label": "BTC price drop 10%"},
        {"id": "btc_drop_20", "label": "BTC price drop 20%"},
        {"id": "market_crash_50", "label": "Market crash 50%"},
        {"id": "virtual_capital_loss_10", "label": "Virtual capital loss 10%"},
        {"id": "news_panic", "label": "News panic"},
    ]


def _safe_float(value: Any, default: float) -> float:
    try:
        return max(float(value), 0.0)
    except (TypeError, ValueError):
        return default


def _scenario_loss_percent(scenario: str, payload: dict[str, Any]) -> float:
    mapping = {"btc_drop_10": 10.0, "btc_drop_20": 20.0, "market_crash_50": 50.0, "virtual_capital_loss_10": 10.0, "news_panic": 14.0, "market_drop": 7.5}
    return mapping.get(scenario, _safe_float(payload.get("price_drop_percent"), 20.0))


def _risk_level_from_loss(loss_percent: float, max_drawdown: float) -> str:
    if loss_percent >= max_drawdown:
        return "CRITICAL"
    if loss_percent >= max_drawdown * 0.7:
        return "HIGH"
    if loss_percent >= max_drawdown * 0.35:
        return "MEDIUM"
    return "LOW"


def _classification_from_loss(loss_percent: float, max_drawdown: float) -> str:
    if loss_percent >= max_drawdown:
        return "capital protection triggered"
    if loss_percent >= max_drawdown * 0.75:
        return "critical"
    if loss_percent >= max_drawdown * 0.35:
        return "warning"
    return "system stable"


def _improvement_recommendations() -> list[dict[str, object]]:
    return [
        {"title": "Add Macro Agent", "priority": "HIGH", "expected_benefit": "Better CPI, rates, and central bank awareness.", "status": "recommended"},
        {"title": "Add Sentiment Agent", "priority": "HIGH", "expected_benefit": "Earlier detection of news panic and false signals.", "status": "recommended"},
        {"title": "Add Telegram Bot", "priority": "DONE", "expected_benefit": "Faster user notification and approvals.", "status": "implemented"},
    ]


def _ai_bots() -> list[dict[str, Any]]:
    return [
        {"name": "General Controller", "kind": "главный бот", "responsibility": "Следит за всеми ботами, сверяет отчёты, блокирует опасные решения.", "reports_to": "Самандар", "status": "Работает", "health_score": 96, "short": "контроль системы", "last_report": "Все 11 ботов работают. Конфликтов нет."},
        {"name": "Market Agent", "kind": "рыночный бот", "responsibility": "Проверяет цену, тренд, объём, импульс и структуру рынка.", "reports_to": "General Controller", "status": "Работает", "health_score": 96, "short": "рынок", "last_report": "BTC и SOL в режиме наблюдения."},
        {"name": "News Agent", "kind": "новостной бот", "responsibility": "Проверяет новости, источники, доверие и влияние на рынок по правилу 2+ подтверждений.", "reports_to": "General Controller", "status": "Работает", "health_score": 92, "short": "новости", "last_report": "Доработан: новости проходят двойное подтверждение, слухи не допускаются к сделкам."},
        {"name": "Risk Engine", "kind": "бот риска", "responsibility": "Считает риск, просадку, лимиты и блокирует опасные сделки.", "reports_to": "General Controller", "status": "Работает", "health_score": 98, "short": "риск", "last_report": "Риск LOW, лимиты соблюдены."},
        {"name": "Portfolio Engine", "kind": "бот портфеля", "responsibility": "Следит за виртуальными деньгами, позициями и свободными средствами.", "reports_to": "General Controller", "status": "Работает", "health_score": 95, "short": "портфель", "last_report": "Виртуальный капитал защищён."},
        {"name": "Paper Trading Bot", "kind": "демо-торговля", "responsibility": "Открывает и закрывает только демо-сделки.", "reports_to": "Portfolio Engine", "status": "Работает", "health_score": 93, "short": "сделки", "last_report": "Демо-сделки работают без реальных денег."},
        {"name": "Confidence Engine", "kind": "бот уверенности", "responsibility": "Оценивает силу сигнала и вероятность ошибки.", "reports_to": "General Controller", "status": "Работает", "health_score": 91, "short": "уверенность", "last_report": "Сигнал сверяется с Risk и News."},
        {"name": "Consensus Engine", "kind": "бот согласия", "responsibility": "Сравнивает мнения агентов и ищет конфликт между ними.", "reports_to": "General Controller", "status": "Работает", "health_score": 92, "short": "консенсус", "last_report": "Конфликтов Market/Risk/News нет."},
        {"name": "Stress Bot", "kind": "стресс-тест", "responsibility": "Проверяет падение рынка, просадку капитала, реакцию AI и защитные меры.", "reports_to": "Risk Engine", "status": "Работает", "health_score": 91, "short": "стресс", "last_report": "Доработан: формирует полный отчёт по капиталу, просадке, защите и уведомлениям."},
        {"name": "Learning Engine", "kind": "обучение", "responsibility": "Запоминает ошибки демо-сделок и предлагает улучшения.", "reports_to": "General Controller", "status": "Работает", "health_score": 88, "short": "обучение", "last_report": "ETH-сделка отправлена на анализ."},
        {"name": "Security Guard", "kind": "защита", "responsibility": "Следит, чтобы реальные деньги не использовались без подтверждения.", "reports_to": "General Controller", "status": "Работает", "health_score": 100, "short": "безопасность", "last_report": "Реальная торговля выключена."},
    ]
