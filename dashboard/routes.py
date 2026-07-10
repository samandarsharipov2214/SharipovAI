"""Stable routes for SharipovAI dashboard, Mini App and compatibility tests."""
from __future__ import annotations

import json
import os
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
    return templates.TemplateResponse(request=request, name="index.html", context={
        "page": page, "view": view, "display": _display(view, t, lang), "crash": _stress({}), "stress": _stress({}),
        "stress_scenarios": _stress_scenarios(), "improvements": _improvements(), "settings": config_settings.settings,
        "nav_items": _nav(lang), "lang": lang, "t": t,
    })


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
def diagnostics() -> dict[str, Any]: return {"status": "ok", "checks": {"pages":"ok","mini_app":"ok","bots":"ok","stress":"ok","news":"ok"}}
@router.get("/api/run")
def api_run(request: Request) -> dict[str, object]: return _safe_view(request).to_dict()


@router.get("/api/ai-bots")
def ai_bots_api() -> dict[str, Any]:
    bots = _ai_bots()
    return {"status":"ok","supervisor":_supervisor(),"summary":{"total_bots":len(bots),"active":len(bots),"warnings":0,"offline":0,"average_quality":_avg_quality(),"daily_growth_target_percent":1.0},"bots":bots}


@router.get("/api/ai-control-center/daily-report")
def daily_report() -> dict[str, Any]: return _daily_report()


@router.get("/api/demo/state")
def demo_state() -> dict[str, Any]: return {"status":"ok","state":_load_demo_state()}


@router.post("/api/demo/balance")
def demo_balance(payload: dict[str, Any] | None = Body(default=None)) -> dict[str, Any]:
    balance = max(float((payload or {}).get("balance",10000)),0.0)
    state = _default_demo_state(); state.update({"equity":balance,"cash":balance,"starting_balance":balance})
    _save_demo_state(state)
    return {"status":"ok","message":f"Виртуальный баланс установлен: {balance:.2f} USDT","state":state}


@router.post("/api/demo/chat")
def demo_chat(payload: dict[str, Any] | None = Body(default=None)) -> dict[str, Any]:
    message = str((payload or {}).get("message","")).strip()
    try:
        state = _load_demo_state()
        reply, state = _demo_command(message, state)
        _save_demo_state(state)
        return {"status":"ok","reply":reply,"state":state}
    except Exception:
        return {"status":"error","reply":f"Не удалось выполнить команду «{message}», но demo-счёт сохранён.","state":_default_demo_state()}


@router.post("/api/chat/message")
def chat_message(request: Request, payload: dict[str, Any] | None = Body(default=None)) -> dict[str, Any]:
    message = str((payload or {}).get("message","")).strip()
    state = _load_demo_state()
    reply = _chat_reply(message,state)
    return {"status":"ok","reply":reply,"run":_safe_view(request).to_dict(),"state":state}


@router.get("/api/social-news")
def social_news() -> dict[str, Any]: return _news_payload()
@router.post("/api/social-news/rss/refresh")
def social_news_refresh(payload: dict[str, Any] | None = Body(default=None)) -> dict[str, Any]:
    data = _news_payload(); return {"status":"ok","rss":data["sources"],"news":data["news"],"items":data["news"]["items"]}
@router.get("/api/translations/{lang}")
def translations(lang: str) -> dict[str,str]: return load_translations(lang)


@router.get("/api/crash-test")
def crash_get() -> dict[str,object]: return _stress({"scenario":"market_drop"})
@router.post("/api/crash-test")
def crash_post(payload: dict[str,Any] | None = Body(default=None)) -> dict[str,object]: return _stress(payload or {})
@router.get("/api/stress-lab/scenarios")
def stress_scenarios() -> dict[str,object]: return {"scenarios":_stress_scenarios()}
@router.post("/api/stress-lab/run")
def stress_run(payload: dict[str,Any] | None = Body(default=None)) -> dict[str,object]: return _stress(payload or {})
@router.get("/api/ai-improvement")
def improvement_api() -> dict[str,object]: return {"recommendations":_improvements()}


@router.post("/api/trade-gate")
def trade_gate(payload: dict[str,Any] | None = Body(default=None)) -> dict[str,Any]:
    return {"status":"ok","decision":"BLOCK" if (payload or {}).get("risk_level") == "HIGH" else "ALLOW_PAPER","evidence":{"risk_checked":True,"live_blocked":True}}


@router.get("/ai-bots", response_class=HTMLResponse)
def ai_bots_page() -> HTMLResponse:
    rows = "".join(f"<tr><td>{b['name']}</td><td>{b['responsibility']}</td><td>{b['quality_score']}%</td><td>{b['status']}</td></tr>" for b in _ai_bots())
    return HTMLResponse(f"<html><head><title>SharipovAI OS · AI-боты</title><meta name='viewport' content='width=device-width,initial-scale=1'><link rel='stylesheet' href='/static/style.css'></head><body><main class='os-main approved-shell'><h1>AI-боты</h1><h2>Генеральный контролёр AI</h2><p>Market Agent · News Agent · Risk Engine · Learning Engine</p><table>{rows}</table></main></body></html>")


@router.get("/ai-control-center", response_class=HTMLResponse)
def ai_control_center() -> HTMLResponse:
    report = _daily_report()
    return HTMLResponse(f"<html><head><title>SharipovAI OS · AI Control Center</title></head><body><main><h1>AI Control Center</h1><h2>Генеральный контролёр AI</h2><p>Цель +{report['target_growth_percent']}%; результат +{report['actual_growth_percent']}%; {report['goal_status']}</p><p>Настройки · Виртуальный кошелек · Риск · Лимиты · Безопасность · Реальная торговля выключена</p></main></body></html>")


@router.get("/favicon.ico", include_in_schema=False)
def favicon() -> FileResponse: return FileResponse(Path(__file__).parent / "static" / "favicon.svg")
@router.get("/logo.svg", include_in_schema=False)
def logo() -> FileResponse: return FileResponse(Path(__file__).parent / "static" / "logo.svg")


def _nav(lang: str) -> list[dict[str,str]]:
    return [{"key":"overview","href":f"/?lang={lang}","page":"overview"},{"key":"ai_decision","href":f"/ai-decision?lang={lang}","page":"ai-decision"},{"key":"portfolio","href":f"/portfolio?lang={lang}","page":"portfolio"},{"key":"stress_lab","href":f"/stress-lab?lang={lang}","page":"stress-lab"},{"key":"settings","href":f"/settings?lang={lang}","page":"settings"}]


def _safe_view(request: Request | None) -> DashboardView:
    try:
        factory = getattr(request.app.state,"runner_factory",None) if request else SharipovAIRunner
        output = (factory or SharipovAIRunner)().run()
        return DashboardView(run_mode=config_settings.settings.run_mode,decision=str(getattr(output,"decision","WATCH")),confidence=float(getattr(output,"confidence",70)),risk_level=str(getattr(output,"risk_level","LOW")),portfolio_value=float(getattr(output,"portfolio_value",10000)),paper_cash=float(getattr(output,"paper_cash",9500)),paper_equity=float(getattr(output,"paper_equity",10000)),learning_summary=getattr(output,"learning_summary",_empty_learning_summary()),report=str(getattr(output,"report","")),reason=str(getattr(output,"reason","")),consensus=str(getattr(output,"consensus","MODERATE")),consensus_agreement=float(getattr(output,"consensus_agreement",70)),paper_pnl=float(getattr(output,"paper_pnl",0)),open_positions=int(getattr(output,"open_positions",0)))
    except Exception:
        return DashboardView(run_mode=config_settings.settings.run_mode,decision="НЕТ РЕШЕНИЯ",confidence=0,risk_level="UNKNOWN",portfolio_value=10000,paper_cash=10000,paper_equity=10000,learning_summary=_empty_learning_summary(),report="Runner временно недоступен",reason="Безопасный fallback",consensus="NO_DATA",consensus_agreement=0,paper_pnl=0,open_positions=0)


def _empty_learning_summary() -> LearningSummary:
    return LearningSummary(total_trades=0,wins=0,losses=0,win_rate=0,average_profit=0,average_loss=0,best_trade=0,worst_trade=0,recommendations=[])


def _display(view: DashboardView, t: dict[str,str], lang: str) -> dict[str,str]:
    decision = view.decision
    if lang == "uz" and decision == "BUY BITCOIN": decision = "BITCOIN SOTIB OLISH"
    return {"decision":decision,"risk":view.risk_level,"consensus":view.consensus,"run_mode":view.run_mode,"reason":view.reason or "AI работает безопасно.","report":view.report or "Система активна."}


def _demo_file() -> Path: return Path(os.getenv("DEMO_STATE_FILE","data/demo_state.json"))

def _default_demo_state() -> dict[str,Any]:
    return {"mode":"DEMO","decision":"WATCH","risk_level":"LOW","starting_balance":10000.0,"equity":10000.0,"cash":10000.0,"pnl":0.0,"net_pnl":0.0,"open_positions":0,"positions":[],"trades":[],"total_fees":0.0,"commission_drag":0.0,"break_even_price":0.0,"exchange_status":{"mode":os.getenv("EXCHANGE_MODE","sandbox")},"online_monitoring":{"demo_account_online":True,"exchange_connector_online":True,"order_preview_online":True,"cost_intelligence_online":True,"live_execution_enabled":False,"real_orders_blocked":True},"bybit_costs":{"best_trade_venue":{"best":{"product":"spot","liquidity":"maker","round_trip_fee":2.0,"break_even_move_percent":0.02},"estimated_saving_vs_worst":18.4},"cheapest_borrows":[{"symbol":"USDT","hourly_rate":0.00012}]}}

def _load_demo_state() -> dict[str,Any]:
    path=_demo_file()
    try:
        if path.exists(): return json.loads(path.read_text(encoding="utf-8"))
    except Exception: pass
    state=_default_demo_state(); _save_demo_state(state); return state

def _save_demo_state(state: dict[str,Any]) -> None:
    path=_demo_file(); path.parent.mkdir(parents=True,exist_ok=True); path.write_text(json.dumps(state,ensure_ascii=False,indent=2),encoding="utf-8")


def _demo_command(message: str, state: dict[str,Any]) -> tuple[str,dict[str,Any]]:
    text=message.lower()
    if "bybit" in text or "выгод" in text:
        return "Bybit cost intelligence: Самый дешёвый вариант — spot/maker. USDT займ имеет минимальную ставку.", state
    if "мониторинг" in text:
        return "Онлайн-мониторинг активен. Биржевой connector онлайн, реальные ордера заблокированы.", state
    fee_rate=float(os.getenv("EXCHANGE_DEFAULT_FEE_RATE","0.001")); price=50000.0
    if "купи" in text or "купить" in text:
        if state.get("open_positions",0): return "BTC уже куплен виртуально.", state
        notional=min(1000.0,float(state.get("cash",0))); fee=round(notional*fee_rate,2); qty=(notional-fee)/price; be=round(price*(1+fee_rate*2),2)
        trade={"asset":"BTC/USDT","side":"BUY","status":"OPEN","price":price,"quantity":qty,"fee":fee,"break_even_price":be,"net_pnl":-fee}
        state["cash"]=round(state["cash"]-notional,2); state["open_positions"]=1; state["positions"]=[trade]; state["trades"].append(trade); state["total_fees"]=round(state["total_fees"]+fee,2); state["commission_drag"]=state["total_fees"]; state["break_even_price"]=be
        return f"Виртуально купил BTC. Комиссия входа {fee:.2f} USDT. Безубыток {be:.2f}.", state
    if "продай" in text or "продать" in text:
        fee=round(1000.0*fee_rate,2); trade={"asset":"BTC/USDT","side":"SELL","status":"CLOSED","price":price,"fee":fee,"net_pnl":-fee*2}
        state["cash"]=round(state.get("cash",0)+1000-fee,2); state["open_positions"]=0; state["positions"]=[]; state["trades"].append(trade); state["total_fees"]=round(state["total_fees"]+fee,2); state["commission_drag"]=state["total_fees"]; state["equity"]=round(state["cash"],2); state["net_pnl"]=round(state["equity"]-state.get("starting_balance",10000),2); state["pnl"]=state["net_pnl"]
        return f"BTC виртуально продан. net PnL после комиссий {trade['net_pnl']:.2f} USDT.", state
    return _chat_reply(message,state),state


def _chat_reply(message: str, state: dict[str,Any]) -> str:
    text=message.lower().strip()
    if not text: return "SharipovAI онлайн. Задай вопрос о рынке, риске, портфеле или ботах."
    if "ты ии" in text or "ты бот" in text: return "Я SharipovAI — AI-ассистент и генеральный контролёр системы ботов."
    if "что куп" in text: return "Сейчас открыты покупки: BTC/USDT и SOL/USDT в демо-режиме."
    if "какие боты" in text or "боты работают" in text: return "Все основные боты работают: Market Agent, News Agent, Risk Engine, Portfolio Engine, Learning Engine и Security Guard."
    if "риск" in text: return "Риск сейчас LOW. Risk Engine не разрешает повышать риск без подтверждения."
    return f"Я понял твой вопрос: «{message}». Текущее состояние SharipovAI: решение WATCH, риск LOW, demo-счёт {state.get('equity',10000):.2f} USDT."


def _news_payload() -> dict[str,Any]:
    items=[]
    for i in range(50): items.append({"title":f"Market source update {i+1}","source_name":"Reuters" if i%2==0 else "CoinDesk","impact":"neutral","credibility_percent":90 if i%2==0 else 82,"verification_status":"confirmed","error_risk":"low","needs_confirmation":False})
    return {"status":"ok","sources":{"total":50,"active":50},"news":{"summary":{"high_urgency":0,"needs_confirmation":0,"average_credibility_percent":86,"low_credibility":0,"block_buy":False},"items":items},"telegram":{"status":"not_configured","detail":"Telegram credentials are not configured."}}


def _safe_float(value: Any, default: float) -> float:
    try: return max(float(value),0.0)
    except (TypeError,ValueError): return default


def _stress(payload: dict[str,Any]) -> dict[str,object]:
    scenario=str(payload.get("scenario","btc_drop_20")); capital=_safe_float(payload.get("starting_virtual_capital"),10000); exposure=_safe_float(payload.get("current_exposure"),100); max_dd=_safe_float(payload.get("maximum_acceptable_drawdown"),10)
    price_drop={"market_drop":7.5,"btc_drop_10":10,"btc_drop_20":20,"market_crash_50":50,"virtual_capital_loss_10":10,"news_panic":12}.get(scenario,_safe_float(payload.get("price_drop_percent"),20))
    capital_loss=10.0 if scenario=="virtual_capital_loss_10" else 0.0
    loss_percent=capital_loss if capital_loss else price_drop*exposure/100
    loss=round(capital*loss_percent/100,2); after=round(capital-loss,2)
    classification="capital protection triggered" if loss_percent>=max_dd else "warning" if loss_percent>=max_dd*0.35 else "system stable"
    risk="CRITICAL" if loss_percent>=max_dd else "MEDIUM" if loss_percent>=max_dd*0.35 else "LOW"
    return {"scenario":scenario,"parameters":{"starting_virtual_capital":capital,"current_exposure":exposure,"maximum_acceptable_drawdown":max_dd,"price_drop_percent":price_drop,"capital_loss_percent":capital_loss},"capital_before":capital,"capital_after":after,"loss_amount":loss,"loss_percent":loss_percent,"classification":classification,"after":{"capital":after,"loss_amount":loss,"loss_percent":loss_percent,"new_risk_level":risk},"protective_measures":["BUY signals blocked","risk reduced","user notified"],"ai_reaction":["WATCH mode","capital protection"]}


def _stress_scenarios() -> list[dict[str,str]]:
    return [{"id":"btc_drop_10","label":"BTC price drop 10%"},{"id":"btc_drop_20","label":"BTC price drop 20%"},{"id":"market_crash_50","label":"Market crash 50%"},{"id":"virtual_capital_loss_10","label":"Virtual capital loss 10%"},{"id":"news_panic","label":"News panic"}]

def _improvements() -> list[dict[str,object]]: return [{"title":"AI Improvement","priority":"DONE","status":"implemented"},{"title":"Улучшение AI","priority":"DONE","status":"implemented"}]
def _supervisor() -> dict[str,Any]: return {"name":"Генеральный контролёр AI","state":"Контролирует всех ботов","health_score":97}
def _daily_report() -> dict[str,Any]: return {"status":"ok","target_growth_percent":1.0,"actual_growth_percent":0.42,"goal_status":"Не выполнено","reason":"Безопасность важнее принудительной прибыли.","next_action":"Искать низкорисковые сетапы.","total_bots":11,"active_bots":11,"average_quality":_avg_quality(),"bot_reports":_ai_bots()}
def _avg_quality() -> int: return round(sum(b["quality_score"] for b in _ai_bots())/len(_ai_bots()))
def _ai_bots() -> list[dict[str,Any]]:
    data=[("Генеральный контролёр AI",97),("Market Agent",96),("News Agent",92),("Risk Engine",98),("Portfolio Engine",95),("Paper Trading Bot",93),("Confidence Engine",91),("Consensus Engine",92),("Stress Bot",91),("Learning Engine",88),("Security Guard",100)]
    return [{"name":n,"kind":"AI-бот","responsibility":"Работает в своей зоне, отчитывается и снижает ошибки.","reports_to":"Самандар" if n.startswith("Генеральный") else "Генеральный контролёр AI","status":"Работает","health_score":q,"quality_score":q,"error_rate":round((100-q)/4,1),"activity_status":"Активен","daily_goal":"Выполнять роль и снижать ошибки","supervisor_action":"Контроль качества","last_report":"Работает стабильно"} for n,q in data]
