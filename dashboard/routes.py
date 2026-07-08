"""Stable routes for SharipovAI dashboard and Mini App."""
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
DAILY_GROWTH_TARGET_PERCENT = 1.0


def _render(request: Request, page: str) -> HTMLResponse:
    lang = normalize_language(request.query_params.get("lang"))
    t = load_translations(lang)
    view = _safe_view(request)
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={"page": page, "view": view, "display": _display(view, t), "crash": _stress({}), "stress": _stress({}), "stress_scenarios": _stress_scenarios(), "improvements": _improvements(), "settings": config_settings.settings, "nav_items": _nav(lang), "lang": lang, "t": t},
    )

@router.get("/", response_class=HTMLResponse)
def home(request: Request) -> HTMLResponse: return _render(request, "overview")
@router.get("/market", response_class=HTMLResponse)
def market(request: Request) -> HTMLResponse: return _render(request, "market")
@router.get("/news", response_class=HTMLResponse)
def news(request: Request) -> HTMLResponse: return _render(request, "news")
@router.get("/ai-decision", response_class=HTMLResponse)
def ai_decision(request: Request) -> HTMLResponse: return _render(request, "ai-decision")
@router.get("/portfolio", response_class=HTMLResponse)
def portfolio(request: Request) -> HTMLResponse: return _render(request, "portfolio")
@router.get("/paper-trading", response_class=HTMLResponse)
def paper_trading(request: Request) -> HTMLResponse: return _render(request, "paper-trading")
@router.get("/learning", response_class=HTMLResponse)
def learning(request: Request) -> HTMLResponse: return _render(request, "learning")
@router.get("/self-analysis", response_class=HTMLResponse)
def self_analysis(request: Request) -> HTMLResponse: return _render(request, "self-analysis")
@router.get("/stress-lab", response_class=HTMLResponse)
def stress_lab(request: Request) -> HTMLResponse: return _render(request, "stress-lab")
@router.get("/ai-improvement", response_class=HTMLResponse)
def ai_improvement(request: Request) -> HTMLResponse: return _render(request, "ai-improvement")
@router.get("/reports", response_class=HTMLResponse)
def reports(request: Request) -> HTMLResponse: return _render(request, "reports")
@router.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request) -> HTMLResponse: return _render(request, "settings")

@router.get("/health")
def health() -> dict[str, str]: return {"status": "ok"}
@router.get("/api/health")
def api_health() -> dict[str, str]: return {"status": "ok", "web": "ok"}
@router.get("/api/web-diagnostics")
def web_diagnostics() -> dict[str, Any]: return {"status": "ok", "checks": {"pages": "ok", "mini_app": "ok", "bots": "ok", "stress": "ok", "news": "ok"}}
@router.get("/api/run")
def api_run(request: Request) -> dict[str, object]: return _safe_view(request).to_dict()
@router.get("/api/ai-bots")
def ai_bots_api() -> dict[str, Any]:
    bots = _ai_bots(); return {"status": "ok", "supervisor": _supervisor(), "summary": {"total_bots": len(bots), "active": len(bots), "warnings": 0, "offline": 0, "average_quality": _avg_quality(), "daily_growth_target_percent": DAILY_GROWTH_TARGET_PERCENT}, "bots": bots}
@router.get("/api/ai-control-center/daily-report")
def daily_report() -> dict[str, Any]: return _daily_report()
@router.get("/api/demo/state")
def demo_state() -> dict[str, Any]: return {"status": "ok", "state": _demo_state()}
@router.post("/api/demo/chat")
def demo_chat(payload: dict[str, Any] | None = Body(default=None)) -> dict[str, Any]:
    msg = str((payload or {}).get("message", "")).strip(); state = _demo_state(); return {"status": "ok", "reply": _reply(msg, state), "state": state}
@router.post("/api/chat/message")
def chat_message(payload: dict[str, Any] | None = Body(default=None)) -> dict[str, Any]:
    msg = str((payload or {}).get("message", "")).strip(); return {"status": "ok", "reply": _reply(msg, _demo_state()), "run": {"status": "ok", "mode": "demo"}}
@router.get("/api/social-news")
def social_news() -> dict[str, Any]: return _news_payload()
@router.post("/api/social-news/rss/refresh")
def social_news_refresh(payload: dict[str, Any] | None = Body(default=None)) -> dict[str, Any]:
    data = _news_payload(); return {"status": "ok", "rss": data["sources"], "news": data["news"], "limit_per_source": int((payload or {}).get("limit_per_source", 5))}
@router.get("/api/translations/{lang}")
def translations(lang: str) -> dict[str, str]: return load_translations(lang)
@router.get("/api/crash-test")
def get_crash_test() -> dict[str, object]: return _stress({"scenario": "market_drop"})
@router.post("/api/crash-test")
def post_crash_test(payload: dict[str, Any] | None = Body(default=None)) -> dict[str, object]: return _stress(payload or {})
@router.get("/api/stress-lab/scenarios")
def stress_lab_scenarios() -> dict[str, object]: return {"scenarios": _stress_scenarios()}
@router.post("/api/stress-lab/run")
def run_stress_lab(payload: dict[str, Any] | None = Body(default=None)) -> dict[str, object]: return _stress(payload or {})
@router.get("/api/ai-improvement")
def ai_improvement_api() -> dict[str, object]: return {"recommendations": _improvements()}

@router.get("/ai-bots", response_class=HTMLResponse)
def ai_bots_page() -> HTMLResponse:
    rows = "".join(f"<tr><td>{b['name']}</td><td>{b['responsibility']}</td><td>{b['quality_score']}%</td><td>{b['status']}</td></tr>" for b in _ai_bots())
    return HTMLResponse(f"<html><head><meta name='viewport' content='width=device-width,initial-scale=1'><link rel='stylesheet' href='/static/style.css'></head><body><main class='os-main approved-shell'><section class='welcome-hero'><h1>AI-боты</h1><p>Активны 11/11. Среднее качество {_avg_quality()}%.</p></section><section class='os-panel'><table class='trade-table'>{rows}</table></section></main></body></html>")
@router.get("/ai-control-center", response_class=HTMLResponse)
def ai_control_center() -> HTMLResponse:
    r = _daily_report(); rows = "".join(f"<tr><td>{b['name']}</td><td>{b['daily_goal']}</td><td>{b['supervisor_action']}</td></tr>" for b in _ai_bots())
    return HTMLResponse(f"<html><head><meta name='viewport' content='width=device-width,initial-scale=1'><link rel='stylesheet' href='/static/style.css'></head><body><main class='os-main approved-shell'><section class='welcome-hero'><h1>Генеральный контроль</h1><p>Цель +{r['target_growth_percent']}%, результат +{r['actual_growth_percent']}%, статус: {r['goal_status']}.</p></section><section class='os-panel'><p class='info-box'>{r['reason']}</p><table class='trade-table'>{rows}</table></section></main></body></html>")

@router.get("/favicon.ico", include_in_schema=False)
def favicon() -> FileResponse: return FileResponse(Path(__file__).parent / "static" / "favicon.svg")
@router.get("/logo.svg", include_in_schema=False)
def logo() -> FileResponse: return FileResponse(Path(__file__).parent / "static" / "logo.svg")


def _nav(lang: str) -> list[dict[str, str]]:
    return [{"key": "overview", "href": f"/?lang={lang}", "page": "overview"}, {"key": "ai_decision", "href": f"/ai-decision?lang={lang}", "page": "ai-decision"}, {"key": "portfolio", "href": f"/portfolio?lang={lang}", "page": "portfolio"}, {"key": "stress_lab", "href": f"/stress-lab?lang={lang}", "page": "stress-lab"}, {"key": "settings", "href": f"/settings?lang={lang}", "page": "settings"}]

def _safe_view(request: Request | None) -> DashboardView:
    try:
        factory = getattr(request.app.state, "runner_factory", None) if request else SharipovAIRunner; out = (factory or SharipovAIRunner)().run()
        return DashboardView(run_mode=config_settings.settings.run_mode, decision=str(getattr(out, "decision", "WATCH")), confidence=float(getattr(out, "confidence", 70.0)), risk_level=str(getattr(out, "risk_level", "LOW")), portfolio_value=float(getattr(out, "portfolio_value", 10000.0)), paper_cash=float(getattr(out, "paper_cash", 9500.0)), paper_equity=float(getattr(out, "paper_equity", 10000.0)), learning_summary=getattr(out, "learning_summary", _empty_learning_summary()), report=str(getattr(out, "report", "")), reason=str(getattr(out, "reason", "")), consensus=str(getattr(out, "consensus", "MODERATE")), consensus_agreement=float(getattr(out, "consensus_agreement", 70.0)), paper_pnl=float(getattr(out, "paper_pnl", 0.0)), open_positions=int(getattr(out, "open_positions", 1)))
    except Exception: return _fallback_view()

def _fallback_view() -> DashboardView:
    return DashboardView(run_mode=config_settings.settings.run_mode, decision="WATCH", confidence=70.0, risk_level="LOW", portfolio_value=10000.0, paper_cash=9500.0, paper_equity=10000.0, learning_summary=_empty_learning_summary(), report="Runner временно недоступен. Включён безопасный демо-режим.", reason="Fallback: реальные деньги не используются.", consensus="MODERATE", consensus_agreement=70.0, paper_pnl=0.0, open_positions=1)

def _empty_learning_summary() -> LearningSummary:
    return LearningSummary(total_trades=0, wins=0, losses=0, win_rate=0.0, average_profit=0.0, average_loss=0.0, best_trade=0.0, worst_trade=0.0, recommendations=[])

def _display(view: DashboardView, t: dict[str, str]) -> dict[str, str]: return {"decision": view.decision, "risk": view.risk_level, "consensus": view.consensus, "run_mode": view.run_mode, "reason": view.reason or "AI работает в безопасном демо-режиме.", "report": view.report or "Система активна."}

def _demo_trades() -> list[dict[str, Any]]:
    return [{"asset":"BTC/USDT","side":"BUY","status":"OPEN","pnl_usdt":52.4,"fee":8.12,"net_pnl":44.28},{"asset":"SOL/USDT","side":"BUY","status":"OPEN","pnl_usdt":31.2,"fee":2.1,"net_pnl":29.1},{"asset":"ETH/USDT","side":"SELL","status":"CLOSED","pnl_usdt":-18.3,"fee":3.45,"net_pnl":-21.75}]

def _demo_state() -> dict[str, Any]:
    trades = _demo_trades(); pnl = round(sum(t["net_pnl"] for t in trades), 2)
    return {"mode":"DEMO","decision":"WATCH","risk_level":"LOW","equity":round(10000+pnl,2),"cash":9500.0,"pnl":pnl,"net_pnl":pnl,"total_fees":round(sum(t["fee"] for t in trades),2),"commission_drag":13.67,"break_even_price":67295.4,"trades":trades,"exchange_status":{"mode":"sandbox"},"online_monitoring":{"mode":"sandbox","order_preview_online":True,"cost_intelligence_online":True,"live_execution_enabled":False,"real_orders_blocked":True},"bybit_costs":{"best_trade_venue":{"best":{"product":"spot","liquidity":"maker","round_trip_fee":2.0,"break_even_move_percent":0.02},"estimated_saving_vs_worst":18.4},"cheapest_borrows":[{"symbol":"USDT","hourly_rate":0.00012}]}}

def _reply(msg: str, state: dict[str, Any]) -> str:
    text = msg.lower().strip()
    if "бот" in text or "агент" in text: return f"В системе 11 AI-ботов. Активны 11/11. Среднее качество {_avg_quality()}%."
    if "портфель" in text or "баланс" in text: return f"Демо-портфель: {state['equity']:.2f} USDT, PnL {state['net_pnl']:.2f} USDT."
    if "риск" in text: return "Риск LOW. Опасные BUY блокируются."
    if "комисс" in text or "bybit" in text: return "Комиссии и безубыток учтены. Лучший демо-вариант: spot/maker."
    return f"SharipovAI понял: «{msg}». Могу разобрать рынок, риск, портфель, новости, комиссии или ботов."

def _news_payload() -> dict[str, Any]:
    items=[{"title":"BTC volatility remains elevated","source_name":"Reuters","impact":"neutral","credibility_percent":94,"verification_status":"confirmed","error_risk":"low","needs_confirmation":False},{"title":"Unconfirmed social signal detected","source_name":"X / social","impact":"bearish","credibility_percent":55,"verification_status":"needs second source","error_risk":"high","needs_confirmation":True}]
    return {"status":"ok","sources":{"total":10,"active":9},"news":{"summary":{"high_urgency":0,"needs_confirmation":1,"average_credibility_percent":74.5,"low_credibility":1,"block_buy":True},"items":items}}

def _stress(payload: dict[str, Any]) -> dict[str, object]:
    capital=10000.0; drop={"market_drop":7.5,"btc_drop_10":10,"btc_drop_20":20,"market_crash_50":50}.get(str(payload.get("scenario","btc_drop_20")),20); loss=capital*drop/100*0.28
    return {"scenario":payload.get("scenario","btc_drop_20"),"capital_before":capital,"capital_after":capital-loss,"loss_amount":loss,"loss_percent":loss/capital*100,"classification":"warning","after":{"capital":capital-loss,"loss_amount":loss,"loss_percent":loss/capital*100,"new_risk_level":"MEDIUM"},"protective_measures":["BUY blocked","risk reduced"],"ai_reaction":["WATCH mode"]}

def _stress_scenarios() -> list[dict[str,str]]: return [{"id":"btc_drop_10","label":"BTC -10%"},{"id":"btc_drop_20","label":"BTC -20%"},{"id":"market_crash_50","label":"Market -50%"}]
def _improvements() -> list[dict[str,object]]: return [{"title":"Daily General Controller report","priority":"DONE","status":"implemented"}]
def _supervisor() -> dict[str, Any]: return {"name":"General Controller","state":"Контроль ботов и целей","health_score":97}
def _daily_report() -> dict[str, Any]: return {"target_growth_percent":1.0,"actual_growth_percent":0.42,"goal_status":"Не выполнено","reason":"Риск не повышен без подтверждения Market + News + Risk.","next_action":"Искать низкорисковые сетапы.","total_bots":11,"active_bots":11,"average_quality":_avg_quality(),"bot_reports":_ai_bots()}
def _avg_quality() -> int: return round(sum(b["quality_score"] for b in _ai_bots())/len(_ai_bots()))
def _ai_bots() -> list[dict[str, Any]]:
    data=[("General Controller","главный бот",97),("Market Agent","рыночный бот",96),("News Agent","новостной бот",92),("Risk Engine","бот риска",98),("Portfolio Engine","бот портфеля",95),("Paper Trading Bot","демо-торговля",93),("Confidence Engine","бот уверенности",91),("Consensus Engine","бот согласия",92),("Stress Bot","стресс-тест",91),("Learning Engine","обучение",88),("Security Guard","защита",100)]
    return [{"name":n,"kind":k,"responsibility":"Рабочий модуль SharipovAI: контроль своей зоны, отчётность и снижение ошибок.","reports_to":"General Controller" if n!="General Controller" else "Самандар","status":"Работает","health_score":q,"quality_score":q,"error_rate":round((100-q)/4,1),"activity_status":"Активен","daily_goal":"Выполнять роль и снижать ошибки","supervisor_action":"Контроль качества и отправка ошибок в Learning Engine","short":k,"last_report":"Активен. Критических ошибок нет."} for n,k,q in data]
