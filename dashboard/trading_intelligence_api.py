"""Public Trading Intelligence endpoints for SharipovAI."""

from __future__ import annotations

from html import escape
from typing import Any

from fastapi import Body, FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse

from ai_evidence import system_scoreboard
from learning_engine_v2 import learning_state, propose_lesson
from news_monitor.agents import run_news_agents
from trading_intelligence import market_regime, trade_gate

from .policy_guard import check_dashboard_action, guarded_response


def install_trading_intelligence_api(app: FastAPI) -> None:
    """Install trading intelligence, scoreboards, and learning endpoints."""

    if getattr(app.state, "trading_intelligence_api_installed", False):
        return
    app.state.trading_intelligence_api_installed = True

    @app.get("/api/ai-scoreboard")
    def ai_scoreboard_api() -> dict[str, Any]:
        agents_report = run_news_agents()
        return system_scoreboard(list(agents_report.get("agents", [])))

    @app.get("/ai-scoreboard", response_class=HTMLResponse)
    def ai_scoreboard_page() -> HTMLResponse:
        agents_report = run_news_agents()
        scoreboard = system_scoreboard(list(agents_report.get("agents", [])))
        return HTMLResponse(_render_scoreboard(scoreboard))

    @app.get("/api/market-regime")
    def market_regime_api() -> dict[str, Any]:
        return market_regime()

    @app.post("/api/market-regime")
    def market_regime_post(payload: dict[str, Any] | None = Body(default=None)) -> dict[str, Any]:
        return market_regime(payload or {})

    @app.get("/api/trade-gate")
    def trade_gate_api(request: Request) -> dict[str, Any] | JSONResponse:
        decision = check_dashboard_action(action_type="trade", actor="trade_gate", topic="trading", request=request)
        if decision.get("allowed") is False:
            return JSONResponse(status_code=403, content=guarded_response(decision))
        gate = trade_gate()
        if decision.get("decision") == "caution":
            gate.setdefault("warnings", []).append("Policy Guard: действие разрешено только в осторожном режиме.")
            gate["policy_guard"] = decision
        return gate

    @app.post("/api/trade-gate")
    def trade_gate_post(request: Request, payload: dict[str, Any] | None = Body(default=None)) -> dict[str, Any] | JSONResponse:
        decision = check_dashboard_action(action_type="trade", actor="trade_gate", topic="trading", request=request, extra={"payload_keys": sorted((payload or {}).keys())})
        if decision.get("allowed") is False:
            return JSONResponse(status_code=403, content=guarded_response(decision))
        gate = trade_gate(payload or {})
        if decision.get("decision") == "caution":
            gate.setdefault("warnings", []).append("Policy Guard: действие разрешено только в осторожном режиме.")
            gate["policy_guard"] = decision
        return gate

    @app.get("/trade-gate", response_class=HTMLResponse)
    def trade_gate_page() -> HTMLResponse:
        return HTMLResponse(_render_trade_gate(trade_gate()))

    @app.get("/api/learning-v2")
    def learning_v2_api() -> dict[str, Any]:
        return learning_state()

    @app.post("/api/learning-v2/propose")
    def learning_v2_propose(request: Request, payload: dict[str, Any] | None = Body(default=None)) -> dict[str, Any] | JSONResponse:
        decision = check_dashboard_action(action_type="bot_learning", actor="learning_engine", topic="bot_learning", request=request, extra={"payload_keys": sorted((payload or {}).keys())})
        if decision.get("allowed") is False:
            return JSONResponse(status_code=403, content=guarded_response(decision))
        result = propose_lesson(payload or {})
        if decision.get("decision") == "caution":
            result["policy_guard"] = decision
        return result

    @app.get("/learning-v2", response_class=HTMLResponse)
    def learning_v2_page() -> HTMLResponse:
        return HTMLResponse(_render_learning(learning_state()))


def _page(title: str, body: str) -> str:
    return f"""<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>SharipovAI · {escape(title)}</title><style>{_css()}</style></head><body><main>{body}</main></body></html>"""


def _css() -> str:
    return "body{margin:0;background:#070b12;color:#eef4ff;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif}main{padding:18px;max-width:1180px;margin:auto}.card{background:#111827;border:1px solid #243044;border-radius:18px;padding:16px;margin:12px 0;box-shadow:0 20px 60px rgba(0,0,0,.25)}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:10px}.stat{background:#0b1220;border:1px solid #1f2a3d;border-radius:14px;padding:12px}.stat small{display:block;color:#8ea2c4}.stat b{font-size:22px}table{width:100%;border-collapse:collapse}td,th{padding:10px;border-bottom:1px solid #243044;text-align:left;vertical-align:top}small{display:block;color:#8ea2c4;margin-top:4px}a{color:#60a5fa;font-weight:800}.ok{display:inline-block;background:#10b981;color:#03130d;border-radius:999px;padding:7px 12px;font-weight:900}.warn{display:inline-block;background:#f59e0b;color:#120a02;border-radius:999px;padding:7px 12px;font-weight:900}.bad{display:inline-block;background:#ef4444;color:#fff;border-radius:999px;padding:7px 12px;font-weight:900}@media(max-width:720px){table{font-size:13px}td,th{padding:8px}}"


def _render_scoreboard(scoreboard: dict[str, Any]) -> str:
    counts = scoreboard.get("counts", {})
    rows = "".join(_scoreboard_row(agent) for agent in scoreboard.get("agents", []))
    body = f"""<section class="card"><span class="ok">AI SCOREBOARD</span><h1>Честная панель живости ИИ</h1><p>Здесь видно, кто реально живой, кто работает в demo, кто ждёт API, а кто заглушка.</p><p><a href="/">Главная</a> · <a href="/system-ai-audit">Полный аудит</a> · <a href="/trade-gate">Можно ли торговать?</a></p></section><section class="card"><div class="grid"><div class="stat"><small>Всего AI</small><b>{scoreboard.get('total', 0)}</b></div><div class="stat"><small>Live</small><b>{counts.get('live', 0)}</b></div><div class="stat"><small>Demo</small><b>{counts.get('demo', 0)}</b></div><div class="stat"><small>Ждут API</small><b>{counts.get('waiting_api', 0)}</b></div><div class="stat"><small>Disabled</small><b>{counts.get('disabled', 0)}</b></div><div class="stat"><small>Proof score</small><b>{scoreboard.get('average_proof_score', 0)}</b></div></div></section><section class="card"><h2>AI Evidence Log</h2><table><thead><tr><th>AI</th><th>Data status</th><th>Last update</th><th>Proof</th><th>Honesty</th><th>Evidence</th><th>Missing</th></tr></thead><tbody>{rows}</tbody></table></section>"""
    return _page("AI Scoreboard", body)


def _scoreboard_row(agent: dict[str, Any]) -> str:
    status = str(agent.get("real_data_status", "disabled"))
    css = "ok" if status == "live" else "warn" if status in {"demo", "waiting_api"} else "bad"
    evidence = "<br>".join(escape(str(item)) for item in agent.get("evidence", []))
    missing = "<br>".join(escape(str(item)) for item in agent.get("missing", []))
    return f"<tr><td><b>{escape(str(agent.get('name', 'AI')))}</b><small>{escape(str(agent.get('id', '')))}</small></td><td><span class='{css}'>{escape(status)}</span></td><td>{escape(str(agent.get('last_real_update') or 'нет'))}</td><td>{escape(str(agent.get('proof_score', 0)))}</td><td>{escape(str(agent.get('honesty_label', '')))}</td><td><small>{evidence}</small></td><td><small>{missing}</small></td></tr>"


def _render_trade_gate(gate: dict[str, Any]) -> str:
    decision = str(gate.get("decision", "UNKNOWN"))
    css = "bad" if decision == "BLOCK" else "warn" if decision == "DEMO_ONLY" else "ok"
    blockers = "".join(f"<li>{escape(str(item))}</li>" for item in gate.get("blockers", [])) or "<li>Критических блокеров нет.</li>"
    warnings = "".join(f"<li>{escape(str(item))}</li>" for item in gate.get("warnings", [])) or "<li>Предупреждений нет.</li>"
    regime = gate.get("market_regime", {})
    body = f"""<section class="card"><span class="{css}">{escape(decision)}</span><h1>Можно ли сейчас торговать?</h1><p>{escape(str(gate.get('human_answer', '')))}</p><p><a href="/">Главная</a> · <a href="/ai-scoreboard">AI Scoreboard</a> · <a href="/api/trade-gate">JSON</a></p></section><section class="card"><div class="grid"><div class="stat"><small>Demo</small><b>{'ДА' if gate.get('can_trade_demo') else 'НЕТ'}</b></div><div class="stat"><small>LIVE</small><b>{'ДА' if gate.get('can_trade_live') else 'НЕТ'}</b></div><div class="stat"><small>Режим рынка</small><b>{escape(str(regime.get('regime', 'unknown')))}</b></div><div class="stat"><small>Риск</small><b>{escape(str(regime.get('risk_level', 'unknown')))}</b></div></div></section><section class="card"><h2>Блокеры</h2><ol>{blockers}</ol></section><section class="card"><h2>Предупреждения</h2><ol>{warnings}</ol></section>"""
    return _page("Trade Gate", body)


def _render_learning(state: dict[str, Any]) -> str:
    lessons = "".join(f"<tr><td><b>{escape(str(item.get('error_type')))}</b><small>{escape(str(item.get('source')))}</small></td><td>{escape(str(item.get('lesson')))}</td><td>{escape(str(item.get('new_rule')))}</td><td>{escape(str(item.get('status')))}</td></tr>" for item in state.get("active_rule_candidates", []))
    missing = "".join(f"<li>{escape(str(item))}</li>" for item in state.get("missing", []))
    body = f"""<section class="card"><span class="warn">LEARNING V2</span><h1>Learning Engine 2.0</h1><p>Ошибки должны превращаться в уроки, а уроки — в кандидаты правил.</p><p><a href="/">Главная</a> · <a href="/api/learning-v2">JSON</a></p></section><section class="card"><div class="grid"><div class="stat"><small>Уроков</small><b>{state.get('lesson_count', 0)}</b></div><div class="stat"><small>Режим</small><b>{escape(str(state.get('mode', 'unknown')))}</b></div></div></section><section class="card"><h2>Активные кандидаты правил</h2><table><thead><tr><th>Ошибка</th><th>Урок</th><th>Новое правило</th><th>Статус</th></tr></thead><tbody>{lessons}</tbody></table></section><section class="card"><h2>Что ещё нужно</h2><ol>{missing}</ol></section>"""
    return _page("Learning Engine 2.0", body)
