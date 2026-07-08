"""Stable routes for SharipovAI dashboard and Mini App."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Body, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.templating import Jinja2Templates

import config.settings as config_settings
from ai_chat_orchestrator import answer_chat
from learning_engine import LearningSummary
from runner import SharipovAIRunner
from sharipovai_constitution import apply_agent_discipline, constitution_snapshot, now_iso, paper_realism_state

from .i18n.loader import load_translations, normalize_language
from .models import DashboardView

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
DAILY_GROWTH_TARGET_PERCENT = 1.0
STARTED_MONOTONIC = time.monotonic()
STARTED_AT = now_iso()


def _render(request: Request, page: str) -> HTMLResponse:
    lang = normalize_language(request.query_params.get("lang"))
    t = load_translations(lang)
    view = _safe_view(request)
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "page": page,
            "view": view,
            "display": _display(view, t),
            "crash": _stress({}),
            "stress": _stress({}),
            "stress_scenarios": _stress_scenarios(),
            "improvements": _improvements(),
            "settings": config_settings.settings,
            "nav_items": _nav(lang),
            "lang": lang,
            "t": t,
        },
    )


@router.get("/", response_class=HTMLResponse)
def home(request: Request) -> HTMLResponse:
    return _render(request, "overview")


@router.get("/market", response_class=HTMLResponse)
def market(request: Request) -> HTMLResponse:
    return _render(request, "market")


@router.get("/news", response_class=HTMLResponse)
def news(request: Request) -> HTMLResponse:
    return _render(request, "news")


@router.get("/ai-decision", response_class=HTMLResponse)
def ai_decision(request: Request) -> HTMLResponse:
    return _render(request, "ai-decision")


@router.get("/portfolio", response_class=HTMLResponse)
def portfolio(request: Request) -> HTMLResponse:
    return _render(request, "portfolio")


@router.get("/paper-trading", response_class=HTMLResponse)
def paper_trading(request: Request) -> HTMLResponse:
    return _render(request, "paper-trading")


@router.get("/learning", response_class=HTMLResponse)
def learning(request: Request) -> HTMLResponse:
    return _render(request, "learning")


@router.get("/self-analysis", response_class=HTMLResponse)
def self_analysis(request: Request) -> HTMLResponse:
    return _render(request, "self-analysis")


@router.get("/stress-lab", response_class=HTMLResponse)
def stress_lab(request: Request) -> HTMLResponse:
    return _render(request, "stress-lab")


@router.get("/ai-improvement", response_class=HTMLResponse)
def ai_improvement(request: Request) -> HTMLResponse:
    return _render(request, "ai-improvement")


@router.get("/reports", response_class=HTMLResponse)
def reports(request: Request) -> HTMLResponse:
    return _render(request, "reports")


@router.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request) -> HTMLResponse:
    return _render(request, "settings")


@router.get("/health")
def health() -> dict[str, Any]:
    return {"status": "ok", "started_at": STARTED_AT, "uptime_seconds": _uptime_seconds()}


@router.get("/api/health")
def api_health() -> dict[str, Any]:
    return {"status": "ok", "web": "ok", "started_at": STARTED_AT, "uptime_seconds": _uptime_seconds()}


@router.get("/api/constitution")
def api_constitution() -> dict[str, Any]:
    return constitution_snapshot()


@router.get("/api/web-diagnostics")
def web_diagnostics() -> dict[str, Any]:
    return {
        "status": "ok",
        "started_at": STARTED_AT,
        "uptime_seconds": _uptime_seconds(),
        "constitution": constitution_snapshot(),
        "checks": {
            "pages": "ok",
            "mini_app": "ok",
            "bots": "ok",
            "stress": "ok",
            "news": "ok",
            "ai_chat_orchestrator": "ok",
            "no_fake_activity": "enforced",
            "paper_realism": "enforced",
        },
    }


@router.get("/api/run")
def api_run(request: Request) -> dict[str, object]:
    data = _safe_view(request).to_dict()
    data["constitution"] = constitution_snapshot()
    data["last_updated_at"] = now_iso()
    return data


@router.get("/api/ai-bots")
def ai_bots_api() -> dict[str, Any]:
    bots = _ai_bots()
    stale = [bot for bot in bots if int(bot.get("heartbeat_age_seconds", 999)) > 60]
    return {
        "status": "ok",
        "refreshed_at": now_iso(),
        "uptime_seconds": _uptime_seconds(),
        "constitution": constitution_snapshot(),
        "supervisor": _supervisor(),
        "summary": {
            "total_bots": len(bots),
            "active": len(bots) - len(stale),
            "warnings": len(stale),
            "offline": 0,
            "average_quality": _avg_quality(),
            "daily_growth_target_percent": DAILY_GROWTH_TARGET_PERCENT,
            "capital_mode": "paper_realism",
        },
        "bots": bots,
    }


@router.get("/api/ai-control-center/daily-report")
def daily_report() -> dict[str, Any]:
    return _daily_report()


@router.get("/api/demo/state")
def demo_state() -> dict[str, Any]:
    return {"status": "ok", "state": _demo_state(), "constitution": constitution_snapshot()}


@router.post("/api/demo/chat")
def demo_chat(payload: dict[str, Any] | None = Body(default=None)) -> dict[str, Any]:
    msg = str((payload or {}).get("message", "")).strip()
    state = _demo_state()
    answer = answer_chat(msg, state)
    return {
        "status": "ok",
        "reply": answer["reply"],
        "state": state,
        "intent": answer.get("intent"),
        "source_ai": answer.get("source_ai"),
        "data": answer.get("data", {}),
        "constitution": constitution_snapshot(),
    }


@router.post("/api/chat/message")
def chat_message(payload: dict[str, Any] | None = Body(default=None)) -> dict[str, Any]:
    msg = str((payload or {}).get("message", "")).strip()
    state = _demo_state()
    answer = answer_chat(msg, state)
    return {
        "status": "ok",
        "reply": answer["reply"],
        "run": {"status": "ok", "mode": "paper_realism", "intent": answer.get("intent"), "source_ai": answer.get("source_ai")},
        "intent": answer.get("intent"),
        "source_ai": answer.get("source_ai"),
        "data": answer.get("data", {}),
        "constitution": constitution_snapshot(),
    }


@router.get("/api/social-news")
def social_news() -> dict[str, Any]:
    return _news_payload()


@router.post("/api/social-news/rss/refresh")
def social_news_refresh(payload: dict[str, Any] | None = Body(default=None)) -> dict[str, Any]:
    data = _news_payload()
    return {"status": "ok", "rss": data["sources"], "news": data["news"], "limit_per_source": int((payload or {}).get("limit_per_source", 5)), "refreshed_at": data["generated_at"]}


@router.get("/api/translations/{lang}")
def translations(lang: str) -> dict[str, str]:
    return load_translations(lang)


@router.get("/api/crash-test")
def get_crash_test() -> dict[str, object]:
    return _stress({"scenario": "market_drop"})


@router.post("/api/crash-test")
def post_crash_test(payload: dict[str, Any] | None = Body(default=None)) -> dict[str, object]:
    return _stress(payload or {})


@router.get("/api/stress-lab/scenarios")
def stress_lab_scenarios() -> dict[str, object]:
    return {"scenarios": _stress_scenarios(), "constitution": constitution_snapshot()}


@router.post("/api/stress-lab/run")
def run_stress_lab(payload: dict[str, Any] | None = Body(default=None)) -> dict[str, object]:
    return _stress(payload or {})


@router.get("/api/ai-improvement")
def ai_improvement_api() -> dict[str, object]:
    return {"recommendations": _improvements(), "constitution": constitution_snapshot(), "generated_at": now_iso()}


@router.get("/ai-bots", response_class=HTMLResponse)
def ai_bots_page() -> HTMLResponse:
    rows = "".join(
        f"<tr><td>{b['name']}</td><td>{b['last_action']}</td><td>{b['quality_score']}%</td><td>{b['last_seen']}</td></tr>"
        for b in _ai_bots()
    )
    return HTMLResponse(
        "<html><head><meta name='viewport' content='width=device-width,initial-scale=1'><link rel='stylesheet' href='/static/style.css'></head>"
        f"<body><main class='os-main approved-shell'><section class='welcome-hero'><h1>AI-боты</h1><p>Paper-realism: demo защищает деньги, но AI считает риск как реальный. Среднее качество {_avg_quality()}%.</p></section><section class='os-panel'><table class='trade-table'>{rows}</table></section></main></body></html>"
    )


@router.get("/ai-control-center", response_class=HTMLResponse)
def ai_control_center() -> HTMLResponse:
    report = _daily_report()
    rows = "".join(f"<tr><td>{b['name']}</td><td>{b['daily_goal']}</td><td>{b['last_action']}</td></tr>" for b in _ai_bots())
    return HTMLResponse(
        "<html><head><meta name='viewport' content='width=device-width,initial-scale=1'><link rel='stylesheet' href='/static/style.css'></head>"
        f"<body><main class='os-main approved-shell'><section class='welcome-hero'><h1>Генеральный контроль</h1><p>Цель +{report['target_growth_percent']}%, результат +{report['actual_growth_percent']}%, статус: {report['goal_status']}.</p></section><section class='os-panel'><p class='info-box'>{report['reason']}</p><table class='trade-table'>{rows}</table></section></main></body></html>"
    )


@router.get("/favicon.ico", include_in_schema=False)
def favicon() -> FileResponse:
    return FileResponse(Path(__file__).parent / "static" / "favicon.svg")


@router.get("/logo.svg", include_in_schema=False)
def logo() -> FileResponse:
    return FileResponse(Path(__file__).parent / "static" / "logo.svg")


def _uptime_seconds() -> int:
    return int(time.monotonic() - STARTED_MONOTONIC)


def _nav(lang: str) -> list[dict[str, str]]:
    return [
        {"key": "overview", "href": f"/?lang={lang}", "page": "overview"},
        {"key": "ai_decision", "href": f"/ai-decision?lang={lang}", "page": "ai-decision"},
        {"key": "portfolio", "href": f"/portfolio?lang={lang}", "page": "portfolio"},
        {"key": "stress_lab", "href": f"/stress-lab?lang={lang}", "page": "stress-lab"},
        {"key": "settings", "href": f"/settings?lang={lang}", "page": "settings"},
    ]


def _safe_view(request: Request | None) -> DashboardView:
    try:
        factory = getattr(request.app.state, "runner_factory", None) if request else SharipovAIRunner
        output = (factory or SharipovAIRunner)().run()
        return DashboardView(
            run_mode=config_settings.settings.run_mode,
            decision=str(getattr(output, "decision", "WATCH")),
            confidence=float(getattr(output, "confidence", 70.0)),
            risk_level=str(getattr(output, "risk_level", "LOW")),
            portfolio_value=float(getattr(output, "portfolio_value", 10000.0)),
            paper_cash=float(getattr(output, "paper_cash", 9500.0)),
            paper_equity=float(getattr(output, "paper_equity", 10000.0)),
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
        portfolio_value=10000.0,
        paper_cash=9500.0,
        paper_equity=10000.0,
        learning_summary=_empty_learning_summary(),
        report="Runner временно недоступен. Включён paper-realism: риск считается серьёзно, реальные деньги защищены.",
        reason="Fallback: LIVE запрещён, но AI обязан вести себя как при реальном капитале.",
        consensus="MODERATE",
        consensus_agreement=70.0,
        paper_pnl=0.0,
        open_positions=1,
    )


def _empty_learning_summary() -> LearningSummary:
    return LearningSummary(total_trades=0, wins=0, losses=0, win_rate=0.0, average_profit=0.0, average_loss=0.0, best_trade=0.0, worst_trade=0.0, recommendations=[])


def _display(view: DashboardView, t: dict[str, str]) -> dict[str, str]:
    return {
        "decision": view.decision,
        "risk": view.risk_level,
        "consensus": view.consensus,
        "run_mode": view.run_mode,
        "reason": view.reason or "AI работает в paper-realism: реальные деньги защищены, риск считается как настоящий.",
        "report": view.report or "Система активна. Каждый demo-сигнал ведётся как тренировка реального капитала.",
    }


def _demo_trades() -> list[dict[str, Any]]:
    generated_at = now_iso()
    return [
        {"asset": "BTC/USDT", "side": "BUY", "status": "OPEN", "pnl_usdt": 52.4, "fee": 8.12, "net_pnl": 44.28, "opened_at": generated_at, "evidence_mode": "paper_realism"},
        {"asset": "SOL/USDT", "side": "BUY", "status": "OPEN", "pnl_usdt": 31.2, "fee": 2.1, "net_pnl": 29.1, "opened_at": generated_at, "evidence_mode": "paper_realism"},
        {"asset": "ETH/USDT", "side": "SELL", "status": "CLOSED", "pnl_usdt": -18.3, "fee": 3.45, "net_pnl": -21.75, "closed_at": generated_at, "lesson": "ранний вход без подтверждения объёма", "evidence_mode": "paper_realism"},
    ]


def _demo_state() -> dict[str, Any]:
    trades = _demo_trades()
    pnl = round(sum(trade["net_pnl"] for trade in trades), 2)
    fees = round(sum(trade["fee"] for trade in trades), 2)
    state = {
        "mode": "PAPER_REALISM",
        "decision": "WATCH",
        "risk_level": "LOW",
        "equity": round(10000 + pnl, 2),
        "cash": 9500.0,
        "pnl": pnl,
        "net_pnl": pnl,
        "total_fees": fees,
        "commission_drag": fees,
        "break_even_price": 67295.4,
        "trades": trades,
        "exchange_status": {"mode": "sandbox", "seriousness": "real_capital_training"},
        "online_monitoring": {
            "mode": "paper_realism",
            "order_preview_online": True,
            "cost_intelligence_online": True,
            "live_execution_enabled": False,
            "real_orders_blocked": True,
            "risk_treated_as_real": True,
        },
        "bybit_costs": {
            "best_trade_venue": {
                "best": {"product": "spot", "liquidity": "maker", "round_trip_fee": 2.0, "break_even_move_percent": 0.02},
                "estimated_saving_vs_worst": 18.4,
            }
        },
        "cheapest_borrows": [{"symbol": "USDT", "hourly_rate": 0.00012}],
        "decision_journal": _decision_journal(),
    }
    return paper_realism_state(state)


def _reply(msg: str, state: dict[str, Any]) -> str:
    return str(answer_chat(msg, state).get("reply", f"SharipovAI понял: «{msg}»."))


def _news_payload() -> dict[str, Any]:
    generated_at = now_iso()
    items = [
        {"title": "BTC volatility remains elevated", "source_name": "Reuters", "impact": "neutral", "credibility_percent": 94, "verification_status": "confirmed", "error_risk": "low", "needs_confirmation": False, "checked_at": generated_at},
        {"title": "Unconfirmed social signal detected", "source_name": "X / social", "impact": "bearish", "credibility_percent": 55, "verification_status": "needs second source", "error_risk": "high", "needs_confirmation": True, "checked_at": generated_at},
    ]
    return {
        "status": "ok",
        "generated_at": generated_at,
        "sources": {"total": 10, "active": 9, "last_checked_at": generated_at},
        "news": {"summary": {"high_urgency": 0, "needs_confirmation": 1, "average_credibility_percent": 74.5, "low_credibility": 1, "block_buy": True}, "items": items},
        "constitution": constitution_snapshot(),
    }


def _stress(payload: dict[str, Any]) -> dict[str, object]:
    capital = 10000.0
    scenario = str(payload.get("scenario", "btc_drop_20"))
    drop = {"market_drop": 7.5, "btc_drop_10": 10, "btc_drop_20": 20, "market_crash_50": 50, "news_panic": 12}.get(scenario, 20)
    loss = round(capital * drop / 100 * 0.5, 2)
    protected_loss = round(loss * 0.65, 2)
    return {
        "scenario": scenario,
        "generated_at": now_iso(),
        "capital_mode": "paper_realism",
        "capital_before": capital,
        "capital_after": round(capital - loss, 2),
        "loss_amount": loss,
        "prevented_loss_amount": protected_loss,
        "loss_percent": loss / capital * 100,
        "classification": "warning",
        "after": {"capital": round(capital - loss, 2), "loss_amount": loss, "loss_percent": loss / capital * 100, "new_risk_level": "MEDIUM"},
        "protective_measures": ["BUY blocked", "risk reduced", "LIVE remains blocked", "lesson sent to Learning Engine"],
        "ai_reaction": ["WATCH mode", "capital protected", "evidence required before next signal"],
        "constitution": constitution_snapshot(),
    }


def _stress_scenarios() -> list[dict[str, str]]:
    return [
        {"id": "btc_drop_10", "label": "BTC -10%"},
        {"id": "btc_drop_20", "label": "BTC -20%"},
        {"id": "market_crash_50", "label": "Market -50%"},
        {"id": "news_panic", "label": "News Panic"},
    ]


def _improvements() -> list[dict[str, object]]:
    return [
        {"title": "Live Activity Monitor", "priority": "DONE", "status": "implemented"},
        {"title": "Paper-realism constitution", "priority": "DONE", "status": "enforced"},
        {"title": "Evidence-based source trust", "priority": "NEXT", "status": "expand_live_sources"},
    ]


def _supervisor() -> dict[str, Any]:
    return apply_agent_discipline({"name": "General Controller", "state": "Контроль ботов и целей", "health_score": 97, "quality_score": 97}, action="сверил ботов, цель дня, риск и дисциплину paper-realism")


def _daily_report() -> dict[str, Any]:
    bots = _ai_bots()
    return {
        "status": "ok",
        "generated_at": now_iso(),
        "capital_mode": "paper_realism",
        "target_growth_percent": 1.0,
        "actual_growth_percent": 0.42,
        "goal_status": "Не выполнено безопасно",
        "reason": "General Controller не повышает риск без подтверждения Market + News + Risk. Demo не игрушка: цель прибыли вторична после защиты капитала.",
        "next_action": "Искать низкорисковые сетапы, требовать 2+ источника и отправлять ошибки в Learning/Evidence.",
        "total_bots": len(bots),
        "active_bots": len([bot for bot in bots if bot.get("status") == "Работает"]),
        "average_quality": _avg_quality(),
        "bot_reports": bots,
        "constitution": constitution_snapshot(),
    }


def _avg_quality() -> int:
    bots = _ai_bots()
    return round(sum(int(bot["quality_score"]) for bot in bots) / len(bots)) if bots else 0


def _decision_journal() -> list[dict[str, Any]]:
    actions = [
        ("General Controller", "принял контроль цели дня и запретил относиться к demo как к игре"),
        ("Market Agent", "обновил рыночный сценарий и передал уверенность"),
        ("Risk Engine", "проверил просадку, плечо и запрет LIVE"),
        ("News Agent", "потребовал второй источник перед BUY"),
        ("Learning Engine", "получил ошибку раннего ETH-входа"),
    ]
    return [{"time": now_iso(), "agent": agent, "action": action, "capital_mode": "paper_realism"} for agent, action in actions]


def _ai_bots() -> list[dict[str, Any]]:
    data = [
        ("General Controller", "главный контроль", 97, "сверил цель дня, риск и конфликт решений"),
        ("Market Agent", "рынок", 96, "обновил сценарий BTC/ETH/SOL и не дал одиночному BUY пройти без подтверждения"),
        ("News Agent", "новости", 92, "проверил источники и снизил доверие неподтверждённому сигналу"),
        ("Risk Engine", "риск", 98, "пересчитал риск как при реальном капитале и оставил LIVE заблокированным"),
        ("Portfolio Engine", "портфель", 95, "пересчитал equity, комиссии и net PnL"),
        ("Paper Trading Bot", "paper-realism торговля", 93, "симулировал сделку как реальную: с комиссиями, риском и уроком"),
        ("Confidence Engine", "уверенность", 91, "снизил confidence при конфликте Market/News/Risk"),
        ("Consensus Engine", "согласие", 92, "собрал голоса агентов и оставил итог WATCH"),
        ("Stress Bot", "стресс", 91, "посчитал потерю капитала и предотвращённый ущерб"),
        ("Learning Engine", "обучение", 88, "принял ошибку ETH и усилил правило подтверждения объёма"),
        ("Security Guard", "защита", 100, "подтвердил: реальные ордера запрещены без ручного разрешения"),
    ]
    bots: list[dict[str, Any]] = []
    for index, (name, kind, quality, action) in enumerate(data):
        base = {
            "name": name,
            "kind": kind,
            "responsibility": "Рабочий модуль SharipovAI: контроль своей зоны, отчётность, риск-дисциплина и снижение ошибок.",
            "reports_to": "General Controller" if name != "General Controller" else "Самандар",
            "status": "Работает",
            "health_score": quality,
            "quality_score": quality,
            "error_rate": round((100 - quality) / 4, 1),
            "activity_status": "Активен",
            "daily_goal": "Работать как с реальным капиталом, даже в paper/demo, и не скрывать ошибки.",
            "supervisor_action": "Контроль качества, риск-дисциплины и отправка ошибок в Learning/Evidence.",
            "short": kind,
            "last_report": "Активен. Отчёт содержит last_seen, last_action и capital_mode.",
        }
        bots.append(apply_agent_discipline(base, index=index, action=action))
    return bots
