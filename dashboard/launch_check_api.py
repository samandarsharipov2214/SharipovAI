"""Final launch check endpoints for SharipovAI.

One page to verify the whole stack before/after Render deploy.
"""

from __future__ import annotations

from html import escape
from typing import Any, Callable

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from ai_chat_orchestrator import answer_chat
from ai_evidence import system_scoreboard
from learning.bot_communication import BotCommunicationNetwork
from learning_engine_v2 import learning_state
from news_monitor.agents import run_news_agents
from news_monitor.analyzer import analyzed_news_payload
from system_ai_auditor import audit_system_ai
from telegram_health import telegram_health
from trading_intelligence import trade_gate

from .bot_communication_api import install_bot_communication_api


def install_launch_check_api(app: FastAPI) -> None:
    """Install launch check endpoints."""

    install_bot_communication_api(app)
    if getattr(app.state, "launch_check_api_installed", False):
        return
    app.state.launch_check_api_installed = True

    @app.get("/api/launch-check")
    def launch_check_api() -> dict[str, Any]:
        return launch_check()

    @app.get("/launch-check", response_class=HTMLResponse)
    def launch_check_page() -> HTMLResponse:
        return HTMLResponse(_render_launch_check(launch_check()))


def launch_check() -> dict[str, Any]:
    """Run a compact final launch check."""

    checks = [
        _check("Backend", "FastAPI app отвечает", lambda: {"status": "ok", "home": "/", "health": "/api/health"}),
        _check("AI Chat Router", "Чат выбирает внутренних AI-ботов", lambda: answer_chat("Что сегодня произошло?", _demo_state())),
        _check("News AI", "Новости и News Supervisor доступны", _news_check),
        _check("Trade Gate", "Риск и решение торговать доступны", trade_gate),
        _check("AI Scoreboard", "real_data_status/proof_score доступны", _scoreboard_check),
        _check("System AI Audit", "Аудит всех ИИ доступен", audit_system_ai),
        _check("Learning Engine 2.0", "Уроки и правила доступны", learning_state),
        _check("Bot Network", "Все 11 AI-ботов имеют канал связи", _bot_network_check),
        _check("Telegram Bot", "BOT_TOKEN/WEBAPP_URL/webhook self-test", telegram_health),
    ]
    failures = [item for item in checks if item["ok"] is False]
    warnings = [item for item in checks if item.get("warning")]
    telegram = checks[-1].get("data", {}) if checks else {}
    next_steps = _next_steps(telegram, failures)
    return {
        "status": "ok" if not failures else "attention",
        "ready_for_deploy": not failures,
        "checks_total": len(checks),
        "checks_ok": sum(1 for item in checks if item["ok"]),
        "checks_failed": len(failures),
        "warnings": len(warnings),
        "checks": checks,
        "next_steps": next_steps,
        "important_urls": {
            "home": "/",
            "bot_network": "/bot-network",
            "bot_network_health": "/api/bot-network/health",
            "telegram_check": "/telegram-check",
            "set_webhook": "/api/telegram/set-webhook",
            "chat_debug": "/chat-debug?q=Что сегодня произошло?",
            "trade_gate": "/trade-gate",
            "ai_scoreboard": "/ai-scoreboard",
            "system_ai_audit": "/system-ai-audit",
            "news_live": "/news-live",
        },
    }


def _check(name: str, description: str, fn: Callable[[], Any]) -> dict[str, Any]:
    try:
        data = fn()
        ok = _is_ok(data)
        warning = _has_warning(data)
        return {"name": name, "description": description, "ok": ok, "warning": warning, "data": data}
    except Exception as exc:  # pragma: no cover
        return {"name": name, "description": description, "ok": False, "warning": True, "error": f"{type(exc).__name__}: {exc}"}


def _is_ok(data: Any) -> bool:
    if not isinstance(data, dict):
        return True
    status = str(data.get("status", "ok"))
    if status in {"error", "failed", "missing_token"}:
        return False
    if data.get("verdict") in {"telegram_error"}:
        return False
    if data.get("full_mesh_possible") is False:
        return False
    return True


def _has_warning(data: Any) -> bool:
    if not isinstance(data, dict):
        return False
    if data.get("verdict") in {"waiting_env", "webhook_not_set", "webhook_error"}:
        return True
    if data.get("status") in {"attention", "warning"}:
        return True
    return False


def _demo_state() -> dict[str, Any]:
    return {"mode": "DEMO", "decision": "WATCH", "risk_level": "LOW", "equity": 10051.63, "net_pnl": 51.63, "total_fees": 13.67}


def _news_check() -> dict[str, Any]:
    news = analyzed_news_payload()
    agents = run_news_agents()
    return {
        "status": "ok",
        "items": len(news.get("items", [])) if isinstance(news, dict) else 0,
        "summary": news.get("summary", {}) if isinstance(news, dict) else {},
        "supervisor": agents.get("supervisor", {}) if isinstance(agents, dict) else {},
        "agent_count": len(agents.get("agents", [])) if isinstance(agents, dict) else 0,
    }


def _scoreboard_check() -> dict[str, Any]:
    agents = run_news_agents()
    return system_scoreboard(list(agents.get("agents", [])))


def _bot_network_check() -> dict[str, Any]:
    return BotCommunicationNetwork().health()


def _next_steps(telegram: Any, failures: list[dict[str, Any]]) -> list[str]:
    steps: list[str] = []
    if failures:
        steps.append("Сначала исправить failed checks на /launch-check, потом деплой.")
    else:
        steps.append("Render → Manual Deploy → Deploy latest commit → дождаться Live.")
    if isinstance(telegram, dict):
        verdict = telegram.get("verdict")
        if verdict in {"waiting_env"}:
            steps.append("В Render Environment Variables проверить BOT_TOKEN и WEBAPP_URL.")
        elif verdict in {"webhook_not_set", "webhook_error"}:
            steps.append("После деплоя открыть /telegram-check и нажать Set webhook.")
        elif verdict == "working":
            steps.append("Telegram webhook уже выглядит рабочим. Написать боту /start.")
        else:
            steps.append("После деплоя открыть /telegram-check и выполнить подсказку Next fix.")
    steps.append("Проверить /bot-network и /api/bot-network/health: full_mesh_possible должен быть true.")
    steps.append("Проверить /chat-debug?q=Что сегодня произошло? перед проверкой Telegram.")
    steps.append("В Telegram проверить /start, /now, /trade, /why, /scoreboard.")
    return steps


def _render_launch_check(report: dict[str, Any]) -> str:
    status = str(report.get("status", "unknown"))
    badge_class = "ok" if status == "ok" else "warn"
    rows = "".join(_check_row(item) for item in report.get("checks", []))
    steps = "".join(f"<li>{escape(str(step))}</li>" for step in report.get("next_steps", []))
    urls = report.get("important_urls", {})
    url_links = "".join(f"<p><a href='{escape(str(url))}'>{escape(str(label))}</a> <small>{escape(str(url))}</small></p>" for label, url in urls.items())
    return f"""<!doctype html>
<html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>SharipovAI · Launch Check</title><style>
body{{margin:0;background:#070b12;color:#eef4ff;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif}}main{{padding:18px;max-width:1180px;margin:auto}}.card{{background:#111827;border:1px solid #243044;border-radius:18px;padding:16px;margin:12px 0;box-shadow:0 20px 60px rgba(0,0,0,.25)}}.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:10px}}.stat{{background:#0b1220;border:1px solid #1f2a3d;border-radius:14px;padding:12px}}.stat small{{display:block;color:#8ea2c4}}.stat b{{font-size:22px}}table{{width:100%;border-collapse:collapse}}td,th{{padding:10px;border-bottom:1px solid #243044;text-align:left;vertical-align:top}}small{{display:block;color:#8ea2c4;margin-top:4px}}a{{color:#60a5fa;font-weight:800}}.ok{{display:inline-block;background:#10b981;color:#03130d;border-radius:999px;padding:7px 12px;font-weight:900}}.warn{{display:inline-block;background:#f59e0b;color:#120a02;border-radius:999px;padding:7px 12px;font-weight:900}}.bad{{display:inline-block;background:#ef4444;color:#fff;border-radius:999px;padding:7px 12px;font-weight:900}}@media(max-width:720px){{table{{font-size:13px}}td,th{{padding:8px}}}}
</style></head><body><main>
<section class="card"><span class="{badge_class}">{escape(status.upper())}</span><h1>Final Launch Check</h1><p>Одна страница для проверки всего перед/после деплоя.</p><p><a href="/">Главная</a> · <a href="/api/launch-check">JSON</a> · <a href="/bot-network">Bot Network</a> · <a href="/telegram-check">Telegram Check</a></p></section>
<section class="card"><div class="grid"><div class="stat"><small>Checks OK</small><b>{report.get('checks_ok', 0)} / {report.get('checks_total', 0)}</b></div><div class="stat"><small>Failed</small><b>{report.get('checks_failed', 0)}</b></div><div class="stat"><small>Warnings</small><b>{report.get('warnings', 0)}</b></div><div class="stat"><small>Ready for deploy</small><b>{'ДА' if report.get('ready_for_deploy') else 'НЕТ'}</b></div></div></section>
<section class="card"><h2>Проверки</h2><table><thead><tr><th>Модуль</th><th>Статус</th><th>Описание</th><th>Деталь</th></tr></thead><tbody>{rows}</tbody></table></section>
<section class="card"><h2>Что делать дальше</h2><ol>{steps}</ol></section>
<section class="card"><h2>Важные ссылки</h2>{url_links}</section>
</main></body></html>"""


def _check_row(item: dict[str, Any]) -> str:
    ok = bool(item.get("ok"))
    warning = bool(item.get("warning"))
    css = "ok" if ok and not warning else "warn" if ok else "bad"
    status = "OK" if ok and not warning else "WARNING" if ok else "FAILED"
    detail = _detail(item)
    return f"<tr><td><b>{escape(str(item.get('name')))}</b></td><td><span class='{css}'>{status}</span></td><td>{escape(str(item.get('description')))}</td><td><small>{escape(detail)}</small></td></tr>"


def _detail(item: dict[str, Any]) -> str:
    if item.get("error"):
        return str(item.get("error"))
    data = item.get("data", {})
    if isinstance(data, dict):
        if data.get("explanation"):
            return str(data.get("explanation"))
        if data.get("reply"):
            return str(data.get("source_ai", "AI"))
        if data.get("full_mesh_possible") is not None:
            return f"full_mesh={data.get('full_mesh_possible')} bots={data.get('bot_count')} messages={data.get('message_count')}"
        if data.get("decision"):
            return f"decision={data.get('decision')}"
        if data.get("verdict"):
            return f"verdict={data.get('verdict')}"
        if data.get("status"):
            return f"status={data.get('status')}"
    return "ok"
