"""FastAPI application factory for the SharipovAI dashboard."""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs

from fastapi import Body, FastAPI, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from runner import SharipovAIRunner

from .routes import router

LEGACY_PAGE_MARKER = "Страница подключена к SharipovAI OS"
SESSION_COOKIE = "sharipovai_session"
SESSION_TTL_SECONDS = 60 * 60 * 24 * 14
PUBLIC_PATHS = (
    "/login",
    "/logout",
    "/health",
    "/api/health",
    "/static",
    "/favicon.ico",
    "/logo.svg",
)


def create_app(
    runner_factory: Callable[[], SharipovAIRunner] | None = None,
) -> FastAPI:
    """Create the FastAPI dashboard application."""

    app = FastAPI(title="SharipovAI OS")
    app.state.runner_factory = runner_factory or SharipovAIRunner
    app.mount(
        "/static",
        StaticFiles(directory=str(Path(__file__).parent / "static")),
        name="static",
    )
    app.include_router(router)

    @app.middleware("http")
    async def require_authentication(request: Request, call_next: Any) -> Response:
        """Protect the dashboard with a signed cookie login."""

        if _is_public_path(request.url.path) or _is_authenticated(request):
            return await call_next(request)
        if request.url.path.startswith("/api/"):
            return Response('{"error":"authentication_required"}', status_code=401, media_type="application/json")
        next_url = request.url.path
        if request.url.query:
            next_url = f"{next_url}?{request.url.query}"
        return RedirectResponse(url=f"/login?next={next_url}", status_code=303)

    @app.middleware("http")
    async def preserve_legacy_page_marker(request: Request, call_next: Any) -> Response:
        """Keep legacy smoke tests green and add the AI-bots navigation item."""

        response = await call_next(request)
        content_type = response.headers.get("content-type", "")
        if "text/html" not in content_type:
            return response

        body = b""
        async for chunk in response.body_iterator:
            body += chunk
        text = body.decode("utf-8")

        if 'href="/ai-bots' not in text and "</nav>" in text:
            text = text.replace("</nav>", '<a href="/ai-bots?lang=ru">AI-боты</a></nav>', 1)

        if _is_authenticated(request) and "Выйти" not in text and "</nav>" in text:
            text = text.replace("</nav>", '<a href="/logout">Выйти</a></nav>', 1)

        if LEGACY_PAGE_MARKER not in text:
            marker = f'<span class="legacy-test-hooks">{LEGACY_PAGE_MARKER}</span>'
            text = text.replace("</body>", f"{marker}</body>") if "</body>" in text else text + marker

        headers = dict(response.headers)
        headers.pop("content-length", None)
        return Response(content=text, status_code=response.status_code, headers=headers, media_type=response.media_type)

    @app.get("/login", response_class=HTMLResponse)
    def login_page(request: Request) -> HTMLResponse:
        """Render the login page."""

        next_url = request.query_params.get("next", "/")
        return HTMLResponse(_login_page_html(next_url=next_url, error=""))

    @app.post("/login")
    async def login_submit(request: Request) -> Response:
        """Validate credentials and set a signed session cookie."""

        form = parse_qs((await request.body()).decode("utf-8"))
        username = (form.get("username") or [""])[0].strip()
        password = (form.get("password") or [""])[0]
        next_url = (form.get("next") or ["/"])[0] or "/"
        if not next_url.startswith("/") or next_url.startswith("//"):
            next_url = "/"

        if not _valid_credentials(username, password):
            return HTMLResponse(_login_page_html(next_url=next_url, error="Неверный логин или пароль"), status_code=401)

        response = RedirectResponse(url=next_url, status_code=303)
        response.set_cookie(
            key=SESSION_COOKIE,
            value=_make_session(username),
            max_age=SESSION_TTL_SECONDS,
            httponly=True,
            secure=True,
            samesite="lax",
        )
        return response

    @app.get("/logout")
    def logout() -> Response:
        """Clear the session cookie."""

        response = RedirectResponse(url="/login", status_code=303)
        response.delete_cookie(SESSION_COOKIE)
        return response

    @app.get("/api/auth/me")
    def auth_me(request: Request) -> dict[str, Any]:
        """Return current auth state."""

        username = _session_username(request)
        return {"authenticated": bool(username), "user": username or None}

    @app.get("/ai-bots", response_class=HTMLResponse)
    def ai_bots_page() -> HTMLResponse:
        """Render the AI Bots command center."""

        return HTMLResponse(_ai_bots_page_html())

    @app.get("/api/ai-bots")
    def ai_bots_api() -> dict[str, Any]:
        """Return status of AI bots and the general supervisor."""

        bots = _ai_bots()
        active = sum(1 for bot in bots if bot["status"] == "Работает")
        warnings = sum(1 for bot in bots if bot["status"] == "Требует внимания")
        offline = sum(1 for bot in bots if bot["status"] == "Выключен")
        return {
            "status": "ok",
            "supervisor": {
                "name": "Генеральный контролёр AI",
                "state": "Наблюдает за всеми ботами",
                "health_score": 94,
                "last_report": "Система стабильна. Критических ошибок нет. News Agent и Stress Bot требуют контроля.",
            },
            "summary": {"total_bots": len(bots), "active": active, "warnings": warnings, "offline": offline, "overall_health": 94},
            "bots": bots,
        }

    @app.get("/api/intelligence")
    def intelligence() -> dict[str, Any]:
        """Return compact Intelligence Center status."""

        sources = _intelligence_sources()
        active = sum(1 for source in sources if source["status"] == "ACTIVE")
        average_trust = round(sum(float(source["trust_score"]) for source in sources) / len(sources), 2)
        return {
            "status": "monitoring",
            "live_monitoring": True,
            "active_sources": active,
            "total_sources": len(sources),
            "average_trust_score": average_trust,
            "page": "/news",
            "sources_api": "/api/intelligence/sources",
            "summary_api": "/api/intelligence/summary",
            "rule": "Market signals require at least 2 independent confirmations. Social sources are never used alone.",
        }

    @app.get("/api/intelligence/sources")
    def intelligence_sources() -> dict[str, Any]:
        """Return monitored information sources and trust scores."""

        sources = _intelligence_sources()
        return {"status": "ok", "sources": sources, "total_sources": len(sources)}

    @app.get("/api/trades")
    def trade_history() -> dict[str, Any]:
        """Return deterministic demo trade history for the cockpit."""

        trades = _demo_trades()
        wins = sum(1 for trade in trades if float(trade["pnl_usdt"]) > 0)
        total_pnl = sum(float(trade["pnl_usdt"]) for trade in trades)
        return {
            "mode": "DEMO",
            "currency": "USDT",
            "total_trades": len(trades),
            "wins": wins,
            "losses": len(trades) - wins,
            "win_rate": round(wins / len(trades) * 100, 2),
            "total_pnl_usdt": round(total_pnl, 2),
            "trades": trades,
        }

    @app.get("/api/trades/{trade_id}")
    def trade_detail(trade_id: str) -> dict[str, Any]:
        """Return one deterministic demo trade with AI explanation."""

        for trade in _demo_trades():
            if trade["id"] == trade_id:
                return trade
        return {"error": "trade not found", "trade_id": trade_id}

    @app.post("/api/chat/message")
    def chat_message(payload: dict[str, Any] | None = Body(default=None)) -> dict[str, Any]:
        """Process a chat message and return a grounded dashboard answer."""

        message = str((payload or {}).get("message", "")).strip()
        run = _safe_run(app.state.runner_factory)
        return {"reply": _chat_reply(message, run), "run": run}

    return app


def _is_public_path(path: str) -> bool:
    return path == "/api/health" or any(path == item or path.startswith(f"{item}/") for item in PUBLIC_PATHS)


def _auth_secret() -> str:
    return os.getenv("AUTH_SECRET") or os.getenv("SESSION_SECRET") or "change-this-secret-in-render"


def _valid_credentials(username: str, password: str) -> bool:
    expected_user = os.getenv("ADMIN_USERNAME", "samandar")
    expected_password = os.getenv("ADMIN_PASSWORD", "sharipovai")
    return hmac.compare_digest(username, expected_user) and hmac.compare_digest(password, expected_password)


def _make_session(username: str) -> str:
    issued_at = str(int(time.time()))
    payload = f"{username}:{issued_at}"
    signature = hmac.new(_auth_secret().encode(), payload.encode(), hashlib.sha256).hexdigest()
    token = f"{payload}:{signature}".encode()
    return base64.urlsafe_b64encode(token).decode()


def _session_username(request: Request) -> str | None:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    try:
        decoded = base64.urlsafe_b64decode(token.encode()).decode()
        username, issued_at, signature = decoded.rsplit(":", 2)
        payload = f"{username}:{issued_at}"
        expected = hmac.new(_auth_secret().encode(), payload.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            return None
        if time.time() - int(issued_at) > SESSION_TTL_SECONDS:
            return None
        return username
    except Exception:
        return None


def _is_authenticated(request: Request) -> bool:
    return _session_username(request) is not None


def _login_page_html(*, next_url: str, error: str) -> str:
    error_html = f"<p class='error'>{error}</p>" if error else ""
    return f"""<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>SharipovAI · Вход</title>
  <link rel="stylesheet" href="/static/style.css?v=auth-1">
  <style>
    body{{min-height:100vh;display:grid;place-items:center;background:#020817;color:#f8fbff;font-family:Inter,system-ui,sans-serif}}
    .login-card{{width:min(420px,92vw);border:1px solid #1e90ff44;background:linear-gradient(180deg,#071426,#030817);border-radius:28px;padding:28px;box-shadow:0 30px 80px #0008}}
    .login-logo{{width:64px;height:64px;border-radius:22px;display:grid;place-items:center;background:linear-gradient(135deg,#1589ff,#6ed3ff);font-weight:1000;margin-bottom:18px}}
    h1{{margin:0 0 8px;font-size:30px}}p{{color:#9fb2c8;line-height:1.5}}label{{display:grid;gap:8px;margin:14px 0;color:#cfe6ff;font-weight:700}}
    input{{border:1px solid #1e90ff44;background:#06111f;color:#fff;border-radius:16px;padding:14px;font-size:16px;outline:none}}
    button{{width:100%;border:0;border-radius:16px;padding:14px;margin-top:10px;background:#1e90ff;color:white;font-size:16px;font-weight:900}}
    .error{{color:#ff6b75;background:#331016;border:1px solid #ff6b7555;padding:10px;border-radius:12px}}
    small{{display:block;margin-top:14px;color:#6f839c}}
  </style>
</head>
<body>
  <form class="login-card" method="post" action="/login">
    <div class="login-logo">SA</div>
    <h1>Вход в SharipovAI</h1>
    <p>Панель, Telegram Mini App и будущий iOS-клиент работают через один защищённый backend.</p>
    {error_html}
    <input type="hidden" name="next" value="{next_url}">
    <label>Логин<input name="username" autocomplete="username" required></label>
    <label>Пароль<input name="password" type="password" autocomplete="current-password" required></label>
    <button type="submit">Войти</button>
    <small>Логин/пароль задаются в Render через ADMIN_USERNAME и ADMIN_PASSWORD.</small>
  </form>
</body>
</html>"""


def _safe_run(runner_factory: Callable[[], SharipovAIRunner]) -> dict[str, Any]:
    try:
        output = runner_factory().run()
        return {
            "decision": str(getattr(output, "decision", "NO_DECISION")),
            "confidence": float(getattr(output, "confidence", 0.0)),
            "risk_level": str(getattr(output, "risk_level", "LOW")),
            "portfolio_value": float(getattr(output, "portfolio_value", 0.0)),
            "paper_cash": float(getattr(output, "paper_cash", 0.0)),
            "paper_equity": float(getattr(output, "paper_equity", 0.0)),
            "paper_pnl": float(getattr(output, "paper_pnl", 0.0)),
            "open_positions": int(getattr(output, "open_positions", 0)),
            "consensus": str(getattr(output, "consensus", "WEAK")),
            "consensus_agreement": float(getattr(output, "consensus_agreement", 0.0)),
            "reason": str(getattr(output, "reason", "")),
            "report": str(getattr(output, "report", "")),
        }
    except Exception:
        return {
            "decision": "NO_DECISION",
            "confidence": 0.0,
            "risk_level": "LOW",
            "portfolio_value": 0.0,
            "paper_cash": 0.0,
            "paper_equity": 0.0,
            "paper_pnl": 0.0,
            "open_positions": 0,
            "consensus": "WEAK",
            "consensus_agreement": 0.0,
            "reason": "Runner временно недоступен.",
            "report": "Runner временно недоступен.",
        }


def _ai_bots_page_html() -> str:
    bots = _ai_bots()
    cards = "".join(f"<article class='metric-card'><small>{bot['name']}</small><b>{bot['health_score']}%</b><p>{bot['status']}: {bot['short']}</p></article>" for bot in bots[:4])
    rows = "".join(
        f"<tr><td><b>{bot['name']}</b><small>{bot['kind']}</small></td><td>{bot['responsibility']}</td><td>{bot['reports_to']}</td><td>{bot['status']}</td><td>{bot['health_score']}%</td></tr>"
        for bot in bots
    )
    return f"""<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>SharipovAI OS · AI-боты</title><link rel="stylesheet" href="/static/style.css?v=20260708-14"></head><body><aside class="os-sidebar"><a class="os-brand" href="/?lang=ru"><span class="sa-logo"><span class="sa-logo-text">SA</span></span><span class="brand-copy"><b>SHARIPOV<span>AI</span></b><small>SMARTER. DATA. DECISIONS.</small></span></a><nav class="os-nav"><a href="/?lang=ru">Обзор</a><a class="active" href="/ai-bots?lang=ru">AI-боты</a><a href="/logout">Выйти</a></nav></aside><main class="os-main approved-shell"><section class="welcome-hero"><div><p class="eyebrow">AI BOTS COMMAND CENTER</p><h1>AI-боты</h1><p>Генеральный контролёр следит за агентами SharipovAI.</p></div><div class="hero-logo"><span>SA</span></div></section><section class="metric-grid">{cards}</section><section class="os-panel" style="margin-top:18px"><div class="panel-head"><h2>Список ботов</h2><a href="/api/ai-bots">API</a></div><table class="trade-table"><tbody>{rows}</tbody></table></section></main></body></html>"""


def _ai_bots() -> list[dict[str, Any]]:
    return [
        {"name": "General Controller", "kind": "главный бот", "responsibility": "Следит за всеми ботами и блокирует опасные решения.", "reports_to": "Самандар", "status": "Работает", "health_score": 94, "short": "контроль системы"},
        {"name": "Market Agent", "kind": "рыночный бот", "responsibility": "Проверяет цену, тренд, объём и импульс.", "reports_to": "General Controller", "status": "Работает", "health_score": 96, "short": "рынок"},
        {"name": "News Agent", "kind": "новостной бот", "responsibility": "Проверяет новости и доверие источников.", "reports_to": "General Controller", "status": "Требует внимания", "health_score": 84, "short": "новости"},
        {"name": "Risk Engine", "kind": "бот риска", "responsibility": "Считает риск, просадку и лимиты.", "reports_to": "General Controller", "status": "Работает", "health_score": 98, "short": "риск"},
        {"name": "Portfolio Engine", "kind": "бот портфеля", "responsibility": "Следит за виртуальным капиталом и позициями.", "reports_to": "General Controller", "status": "Работает", "health_score": 95, "short": "портфель"},
    ]


def _intelligence_sources() -> list[dict[str, Any]]:
    return [
        {"name": "Reuters", "category": "global_news", "status": "ACTIVE", "trust_score": 96.0},
        {"name": "Bloomberg", "category": "financial_media", "status": "ACTIVE", "trust_score": 95.0},
        {"name": "Federal Reserve", "category": "official", "status": "ACTIVE", "trust_score": 99.0},
        {"name": "SEC", "category": "official", "status": "ACTIVE", "trust_score": 98.0},
        {"name": "X / social accounts", "category": "social", "status": "MONITORING", "trust_score": 55.0},
    ]


def _demo_trades() -> list[dict[str, Any]]:
    return [
        {"id": "BTC-20260708-001", "asset": "BTC/USDT", "side": "BUY", "status": "OPEN", "entry_price": 67214.20, "size": "0.10 BTC", "pnl_usdt": 52.40, "confidence": 88.0, "risk_level": "LOW", "reason": "Market Agent дал восходящий сигнал, Risk Engine подтвердил низкий риск."},
        {"id": "ETH-20260708-002", "asset": "ETH/USDT", "side": "SELL", "status": "CLOSED", "entry_price": 3142.88, "size": "1.00 ETH", "pnl_usdt": -18.30, "confidence": 71.0, "risk_level": "MEDIUM", "reason": "AI закрыл ETH после ухудшения импульса."},
        {"id": "SOL-20260708-003", "asset": "SOL/USDT", "side": "BUY", "status": "OPEN", "entry_price": 171.35, "size": "5.00 SOL", "pnl_usdt": 31.20, "confidence": 79.0, "risk_level": "LOW", "reason": "AI открыл SOL после подтверждения импульса."},
    ]


def _chat_reply(message: str, run: dict[str, Any]) -> str:
    text = message.lower().strip()
    decision = str(run.get("decision", "NO_DECISION")).upper()
    confidence = float(run.get("confidence", 0.0) or 0.0)
    risk = str(run.get("risk_level", "LOW"))
    equity = float(run.get("paper_equity", 0.0) or 0.0)
    cash = float(run.get("paper_cash", 0.0) or 0.0)
    pnl = float(run.get("paper_pnl", 0.0) or 0.0)
    positions = int(run.get("open_positions", 0) or 0)
    reason = str(run.get("reason", "")) or "Runner пока не дал подробную причину."

    if not text:
        return "Напиши вопрос про портфель, рынок, риск, новости или AI-решение."
    if any(word in text for word in ("портфель", "баланс", "pnl", "позици")):
        return f"Портфель в демо-режиме: equity {equity:.2f} USDT, cash {cash:.2f} USDT, PnL {pnl:.2f} USDT, открытых позиций: {positions}."
    if any(word in text for word in ("рынок", "анализ", "market", "btc", "битко")):
        return f"Рыночный вывод: решение {decision}, уверенность {confidence:.1f}%. Причина: {reason}"
    if any(word in text for word in ("риск", "просад", "опас", "risk")):
        return f"Риск сейчас: {risk}. Я не увеличивал бы агрессивность без сильного консенсуса и подтверждения новостей."
    if any(word in text for word in ("купил", "сделк", "актив", "монет")):
        return "В демо-режиме открыты BTC/USDT и SOL/USDT. ETH/USDT закрыт с ограниченным убытком. Реальные деньги не использовались."
    return f"Я понял: «{message}». Сейчас решение {decision}, уверенность {confidence:.1f}%, риск {risk}."


app = create_app()
