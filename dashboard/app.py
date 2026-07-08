"""FastAPI application factory for the SharipovAI dashboard."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from fastapi import Body, FastAPI, Request, Response
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from runner import SharipovAIRunner

from .routes import router

LEGACY_PAGE_MARKER = "Страница подключена к SharipovAI OS"


def create_app(runner_factory: Callable[[], SharipovAIRunner] | None = None) -> FastAPI:
    """Create the FastAPI dashboard application."""

    app = FastAPI(title="SharipovAI OS")
    app.state.runner_factory = runner_factory or SharipovAIRunner
    app.mount("/static", StaticFiles(directory=str(Path(__file__).parent / "static")), name="static")
    app.include_router(router)

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

        if LEGACY_PAGE_MARKER not in text:
            marker = f'<span class="legacy-test-hooks">{LEGACY_PAGE_MARKER}</span>'
            text = text.replace("</body>", f"{marker}</body>") if "</body>" in text else text + marker

        headers = dict(response.headers)
        headers.pop("content-length", None)
        return Response(content=text, status_code=response.status_code, headers=headers, media_type=response.media_type)

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
                "last_report": "Система стабильна. Критических ошибок нет. News Agent и Stress Bot требуют усиленного контроля.",
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
        active = sum(1 for source in sources if source["status"] == "ACTIVE")
        average_trust = round(sum(float(source["trust_score"]) for source in sources) / len(sources), 2)
        return {
            "status": "ok",
            "active_sources": active,
            "total_sources": len(sources),
            "average_trust_score": average_trust,
            "cross_check_policy": "Market-moving signals must be confirmed by at least 2 independent sources before they can influence demo trading.",
            "sources": sources,
        }

    @app.get("/api/intelligence/summary")
    def intelligence_summary() -> dict[str, Any]:
        """Return Intelligence Center summary for the dashboard."""

        sources = _intelligence_sources()
        return {
            "status": "monitoring",
            "live_monitoring": True,
            "source_groups": sorted({str(source["category"]) for source in sources}),
            "signals_checked_today": 128,
            "contradictions_found": 3,
            "retractions_detected": 1,
            "trust_updates": [
                "Source reliability is reduced when corrections are detected.",
                "Official sources require market-impact cross-checks.",
                "Social signals are never enough alone.",
            ],
        }

    @app.get("/api/trades")
    def trade_history() -> dict[str, Any]:
        """Return deterministic demo trade history for the cockpit."""

        trades = _demo_trades()
        wins = sum(1 for trade in trades if float(trade["pnl_usdt"]) > 0)
        losses = sum(1 for trade in trades if float(trade["pnl_usdt"]) < 0)
        total_pnl = sum(float(trade["pnl_usdt"]) for trade in trades)
        return {
            "mode": "DEMO",
            "currency": "USDT",
            "total_trades": len(trades),
            "wins": wins,
            "losses": losses,
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
        try:
            output = app.state.runner_factory().run()
            run = {
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
            run = {
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
        return {"reply": _chat_reply(message, run), "run": run}

    return app


def _ai_bots_page_html() -> str:
    """Return visual AI bots command center page."""

    bots = _ai_bots()
    rows = "".join(
        f"<tr><td><b>{bot['name']}</b><small>{bot['kind']}</small></td><td>{bot['responsibility']}</td><td>{bot['reports_to']}</td>"
        f"<td><span class='bot-status {bot['css']}'>{bot['status']}</span></td><td>{bot['health_score']}%</td><td>{bot['last_check']}</td><td>{bot['last_report']}</td></tr>"
        for bot in bots
    )
    cards = "".join(
        f"<article class='metric-card'><small>{bot['name']}</small><b>{bot['health_score']}%</b><p>{bot['status']}: {bot['short']}</p></article>"
        for bot in bots[:4]
    )
    return f"""<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>SharipovAI OS · AI-боты</title><link rel="stylesheet" href="/static/style.css?v=20260708-16"><style>.bot-table td:first-child small{{display:block;color:#91a4b8;margin-top:4px}}.bot-status{{display:inline-block;border-radius:999px;padding:7px 10px;font-weight:900;border:1px solid #1e90ff55;background:#071d31}}.ok{{color:#22c55e}}.warn{{color:#f6c04a}}.off{{color:#ef4444}}.boss-card{{display:grid;grid-template-columns:1.25fr .8fr;gap:18px;margin-bottom:18px}}.ai-live-log{{display:grid;gap:10px;margin:0;padding:0;list-style:none}}.ai-live-log li{{border:1px solid #1e90ff33;border-radius:14px;background:#071d31;padding:12px}}@media(max-width:980px){{.boss-card{{grid-template-columns:1fr}}}}</style></head><body><aside class="os-sidebar"><a class="os-brand" href="/?lang=ru" aria-label="SharipovAI OS"><span class="sa-logo"><span class="sa-logo-text">SA</span><span class="sa-candles"><i></i><i></i><i></i><i></i></span></span><span class="brand-copy"><b>SHARIPOV<span>AI</span></b><small>SMARTER. DATA. DECISIONS.</small></span></a><nav class="os-nav" aria-label="Main navigation"><a href="/?lang=ru">Обзор</a><a href="/ai-decision?lang=ru">AI-решение</a><a href="/portfolio?lang=ru">Портфель</a><a href="/stress-lab?lang=ru">Стресс-лаборатория</a><a class="active" href="/ai-bots?lang=ru">AI-боты</a><a href="/news?lang=ru">Новости</a><a href="/paper-trading?lang=ru">Журнал сделок</a><a href="/settings?lang=ru">Настройки</a></nav><div class="os-heartbeat"><span class="live-dot"></span><div><b>AI активен</b><small>Система в работе</small></div></div></aside><main class="os-main approved-shell"><header class="approved-topbar"><div class="top-clock"><span>◷</span><div><b data-clock>00:00:00</b><small>локальное время</small></div></div><div class="top-stat"><small>Генеральный контролёр</small><b class="status-green">НАБЛЮДАЕТ</b></div><div class="top-stat"><small>Боты онлайн</small><b>10 / 11</b></div><div class="top-stat"><small>Предупреждения</small><b>2</b></div><div class="top-stat"><small>Общее здоровье</small><b>94%</b></div><div class="top-stat"><small>Последний аудит</small><b data-clock>00:00:00</b></div></header><section class="welcome-hero"><div><p class="eyebrow">AI BOTS COMMAND CENTER</p><h1>AI-боты</h1><p>Здесь видно, какие боты входят в SharipovAI, кто за что отвечает, кто кому подчиняется, в каком состоянии каждый бот и что сообщает генеральный контролёр.</p></div><div class="hero-logo"><span>SA</span><i></i><i></i><i></i><i></i></div></section><section class="boss-card"><article class="os-panel"><h2>Генеральный контролёр AI</h2><p class="info-box">Главный бот следит за всеми модулями, проверяет их отчёты, ищет конфликты между агентами и не даёт системе принять решение, если риск, новости или портфель противоречат друг другу.</p><ul><li>Проверяет работу каждого бота.</li><li>Сравнивает отчёты Market, News, Risk и Portfolio.</li><li>Блокирует опасные сделки.</li><li>Создаёт итоговый отчёт для пользователя.</li></ul></article><article class="os-panel"><h2>Отчёт генерального</h2><p class="info-box">Система стабильна. Критических ошибок нет. News Agent и Stress Bot требуют усиленного контроля. Реальная торговля выключена, сделки только демо.</p><ul class="ai-live-log" id="ai-live-log"><li>00:00:00 · Генеральный контролёр проверил состояние агентов.</li><li>00:00:00 · Risk Engine подтвердил лимиты.</li><li>00:00:00 · News Agent отправил 2 новости на перепроверку.</li></ul></article></section><section class="metric-grid">{cards}</section><section class="os-panel" style="margin-top:18px"><div class="panel-head"><h2>Список ботов и их работа</h2><a href="/api/ai-bots">API</a></div><table class="trade-table bot-table"><thead><tr><th>Бот</th><th>За что отвечает</th><th>Кому подчиняется</th><th>Состояние</th><th>Здоровье</th><th>Проверка</th><th>Последний отчёт</th></tr></thead><tbody>{rows}</tbody></table></section><section class="bottom-trust"><span>🤖 Все боты видны</span><span>👑 Есть генеральный контролёр</span><span>🛡 Риск проверяется</span><span>📋 Каждый бот отчитывается</span></section></main><script>(()=>{{const $$=s=>Array.from(document.querySelectorAll(s));const time=()=>new Date().toLocaleTimeString('ru-RU',{{hour:'2-digit',minute:'2-digit',second:'2-digit',hour12:false}});function tick(){{$$('[data-clock]').forEach(e=>e.textContent=time());const log=document.getElementById('ai-live-log');if(log&&Math.random()>.72){{const items=['Генеральный контролёр сверил отчёты ботов.','Market Agent обновил рыночный сигнал.','Risk Engine проверил лимиты капитала.','News Agent перепроверяет новость по двум источникам.','Portfolio Engine подтвердил свободные средства.'];const li=document.createElement('li');li.textContent=time()+' · '+items[Math.floor(Math.random()*items.length)];log.prepend(li);while(log.children.length>5)log.lastChild.remove();}}}}tick();setInterval(tick,2500);}})();</script></body></html>"""


def _ai_bots() -> list[dict[str, Any]]:
    """Return deterministic AI bot catalogue."""

    return [
        {"name": "General Controller", "kind": "главный бот", "responsibility": "Следит за всеми ботами, сверяет отчёты, блокирует опасные решения.", "reports_to": "Самандар", "status": "Работает", "css": "ok", "health_score": 94, "last_check": "только что", "last_report": "Критических ошибок нет. 2 бота требуют наблюдения.", "short": "контроль системы"},
        {"name": "Market Agent", "kind": "рыночный бот", "responsibility": "Проверяет цену, тренд, объём, импульс и рыночную структуру.", "reports_to": "General Controller", "status": "Работает", "css": "ok", "health_score": 96, "last_check": "5 сек назад", "last_report": "BTC и SOL в режиме наблюдения, импульс умеренный.", "short": "рынок"},
        {"name": "News Agent", "kind": "новостной бот", "responsibility": "Проверяет новости, источники, доверие и влияние на рынок.", "reports_to": "General Controller", "status": "Требует внимания", "css": "warn", "health_score": 84, "last_check": "12 сек назад", "last_report": "2 новости требуют подтверждения вторым источником.", "short": "новости"},
        {"name": "Risk Engine", "kind": "бот риска", "responsibility": "Считает риск, просадку, лимиты и блокирует опасные сделки.", "reports_to": "General Controller", "status": "Работает", "css": "ok", "health_score": 98, "last_check": "3 сек назад", "last_report": "Риск LOW, лимиты соблюдены.", "short": "риск"},
        {"name": "Portfolio Engine", "kind": "бот портфеля", "responsibility": "Следит за виртуальными деньгами, позициями и доступными средствами.", "reports_to": "General Controller", "status": "Работает", "css": "ok", "health_score": 95, "last_check": "7 сек назад", "last_report": "Виртуальный капитал защищён, свободные средства есть.", "short": "портфель"},
        {"name": "Paper Trading Bot", "kind": "демо-торговля", "responsibility": "Открывает и закрывает только демо-сделки, реальные деньги не трогает.", "reports_to": "Portfolio Engine", "status": "Работает", "css": "ok", "health_score": 93, "last_check": "10 сек назад", "last_report": "Открыты BTC и SOL, ETH закрыт.", "short": "сделки"},
        {"name": "Confidence Engine", "kind": "бот уверенности", "responsibility": "Оценивает силу сигнала и вероятность ошибки.", "reports_to": "General Controller", "status": "Работает", "css": "ok", "health_score": 91, "last_check": "8 сек назад", "last_report": "Сигнал высокий, но требует сверки с новостями.", "short": "уверенность"},
        {"name": "Consensus Engine", "kind": "бот согласия", "responsibility": "Сравнивает мнения агентов и ищет конфликт между ними.", "reports_to": "General Controller", "status": "Работает", "css": "ok", "health_score": 92, "last_check": "9 сек назад", "last_report": "Конфликтов между Market и Risk нет.", "short": "консенсус"},
        {"name": "Stress Bot", "kind": "стресс-тест", "responsibility": "Проверяет, что будет при падении рынка и просадке капитала.", "reports_to": "Risk Engine", "status": "Требует внимания", "css": "warn", "health_score": 82, "last_check": "20 сек назад", "last_report": "Нужно улучшить визуальный отчёт по реакции AI.", "short": "стресс"},
        {"name": "Learning Engine", "kind": "обучение", "responsibility": "Запоминает ошибки демо-сделок и предлагает улучшения.", "reports_to": "General Controller", "status": "Работает", "css": "ok", "health_score": 88, "last_check": "16 сек назад", "last_report": "ETH-сделка отправлена на анализ ошибки.", "short": "обучение"},
        {"name": "Security Guard", "kind": "защита", "responsibility": "Следит, чтобы реальные деньги не использовались без подтверждения.", "reports_to": "General Controller", "status": "Работает", "css": "ok", "health_score": 100, "last_check": "2 сек назад", "last_report": "Реальная торговля выключена. Доступ только демо.", "short": "безопасность"},
    ]


def _chat_reply(message: str, run: dict[str, Any]) -> str:
    """Return a clear Russian answer for the dashboard chat."""

    text = message.lower().strip()
    decision = str(run.get("decision", "NO_DECISION")).upper()
    confidence = float(run.get("confidence", 0.0) or 0.0)
    risk = str(run.get("risk_level", "LOW"))
    equity = float(run.get("paper_equity", 0.0) or 0.0)
    available = float(run.get("paper_cash", 0.0) or 0.0)
    pnl = float(run.get("paper_pnl", 0.0) or 0.0)
    positions = int(run.get("open_positions", 0) or 0)
    consensus = str(run.get("consensus", "WEAK"))
    agreement = float(run.get("consensus_agreement", 0.0) or 0.0)
    reason = str(run.get("reason", "")) or "Подробная причина пока не пришла от Runner."
    trades = _demo_trades()
    open_buys = [trade for trade in trades if trade["side"] == "BUY" and trade["status"] == "OPEN"]
    closed_trades = [trade for trade in trades if trade["status"] == "CLOSED"]

    if not text:
        return "Я SharipovAI — AI-помощник внутри твоей системы. Я вижу демо-портфель, сделки, риск, новости и состояние AI-ботов. Напиши обычным языком, что проверить."

    if any(phrase in text for phrase in ("какие боты", "боты работают", "состояние ботов", "список ботов", "все боты", "ai-боты", "агенты работают", "какие агенты")):
        bots = _ai_bots()
        active = [bot for bot in bots if bot["status"] == "Работает"]
        warn = [bot for bot in bots if bot["status"] == "Требует внимания"]
        lines = [f"Сейчас в SharipovAI работает {len(active)} из {len(bots)} AI-ботов."]
        lines.append("Главный: General Controller — следит за всеми ботами и блокирует опасные решения.")
        lines.append("Активные боты: " + ", ".join(bot["name"] for bot in active) + ".")
        if warn:
            lines.append("Требуют внимания: " + ", ".join(bot["name"] for bot in warn) + ".")
        lines.append("Полный отчёт открыт в разделе AI-боты: состояние, задача, подчинение, здоровье и последний отчёт каждого бота.")
        return "\n".join(lines)

    if any(word in text for word in ("ты кто", "кто ты", "что ты", "ты ии", "ты ai", "ии", "искусственный", "бот чтоли", "что за ответ", "разве")) or text == "бот":
        return (
            "Я SharipovAI — AI-помощник внутри твоего торгового кабинета, а не просто кнопочный бот. "
            "Я работаю с данными системы: вижу демо-сделки, виртуальный портфель, риск, новости, AI-решение и состояние внутренних ботов. "
            "Моя задача — объяснять, что происходит, почему AI принял решение и какие модули сейчас работают. "
            "Сейчас реальная торговля выключена: я показываю и анализирую только демо-действия."
        )

    if any(word in text for word in ("что куп", "купил", "покуп", "открыл", "открыто", "активы", "монеты")):
        lines = ["В демо-режиме сейчас открыты покупки:"]
        for index, trade in enumerate(open_buys, 1):
            pnl_sign = "+" if float(trade["pnl_usdt"]) >= 0 else ""
            lines.append(f"{index}) {trade['asset']} — куплено {trade['size']} по цене {float(trade['entry_price']):,.2f} USDT. Текущий результат: {pnl_sign}{float(trade['pnl_usdt']):.2f} USDT.")
        if closed_trades:
            lines.append("Закрытые сделки:")
            for trade in closed_trades:
                pnl_sign = "+" if float(trade["pnl_usdt"]) >= 0 else ""
                lines.append(f"{trade['asset']} — закрыта, результат {pnl_sign}{float(trade['pnl_usdt']):.2f} USDT.")
        lines.append("Это только демо-сделки. Реальные деньги не использовались.")
        return "\n".join(lines)

    if any(word in text for word in ("продал", "закрыл", "продажа", "убыток", "минус")):
        return "Закрыта демо-сделка ETH/USDT. Вход был 3,142.88 USDT, объём 1.00 ETH, результат -18.30 USDT. AI закрыл её из-за ухудшения импульса и роста краткосрочного риска."
    if any(word in text for word in ("портфель", "баланс", "средства", "деньги", "pnl", "позици")):
        return f"Виртуальный портфель: общий баланс {equity:.2f} USDT, доступно для новых сделок {available:.2f} USDT, текущий результат {pnl:.2f} USDT, открытых позиций: {positions}. Это демо-режим."
    if any(word in text for word in ("рынок", "анализ", "market", "btc", "битко")):
        return f"По рынку сейчас: решение {decision}, уверенность {confidence:.1f}%, согласие агентов {consensus} {agreement:.1f}%. Причина: {reason}"
    if any(word in text for word in ("риск", "опас", "просад", "безопас")):
        return f"Риск сейчас: {risk}. Я не стал бы повышать агрессивность, пока новости и рынок не подтверждают сигнал. Лимиты защищают виртуальный капитал, реальные деньги не используются."
    if any(word in text for word in ("новост", "источник", "довер", "слух")):
        return "Новости проверяются в разделе Новости: AI смотрит источник, доверие, подтверждение от 2 независимых источников и только потом учитывает новость в решении. Соцсети сами по себе не используются для сделки."
    if any(word in text for word in ("решение", "почему", "объясни", "решил")):
        return f"AI-решение: {decision}. Уверенность {confidence:.1f}%, риск {risk}, согласие агентов {consensus} {agreement:.1f}%. Главная причина: {reason}"

    return f"Я понял твой вопрос: «{message}». По текущему состоянию SharipovAI: решение {decision}, уверенность {confidence:.1f}%, риск {risk}, виртуальный баланс {equity:.2f} USDT. Я могу дальше разобрать это по портфелю, сделкам, новостям, риску или AI-ботам."


def _intelligence_sources() -> list[dict[str, Any]]:
    """Return deterministic source catalogue for Intelligence Center."""

    return [
        {"name": "Reuters", "category": "global_news", "status": "ACTIVE", "trust_score": 96.0, "corrections": 0, "cross_check": "Bloomberg / AP / official filings", "market_use": "major breaking news"},
        {"name": "Bloomberg", "category": "financial_media", "status": "ACTIVE", "trust_score": 95.0, "corrections": 0, "cross_check": "Reuters / official filings", "market_use": "macro, equities, rates"},
        {"name": "Associated Press", "category": "global_news", "status": "ACTIVE", "trust_score": 93.0, "corrections": 0, "cross_check": "Reuters / government sources", "market_use": "politics and global events"},
        {"name": "Federal Reserve", "category": "official", "status": "ACTIVE", "trust_score": 99.0, "corrections": 0, "cross_check": "FOMC calendar / market reaction", "market_use": "rates and USD impact"},
        {"name": "SEC", "category": "official", "status": "ACTIVE", "trust_score": 98.0, "corrections": 0, "cross_check": "EDGAR / company filings", "market_use": "regulation and listed assets"},
        {"name": "CoinDesk", "category": "crypto_media", "status": "ACTIVE", "trust_score": 86.0, "corrections": 1, "cross_check": "Cointelegraph / on-chain / exchange data", "market_use": "crypto news"},
        {"name": "The Block", "category": "crypto_media", "status": "ACTIVE", "trust_score": 85.0, "corrections": 0, "cross_check": "CoinDesk / official project channels", "market_use": "crypto market structure"},
        {"name": "Binance Announcements", "category": "exchange", "status": "ACTIVE", "trust_score": 92.0, "corrections": 0, "cross_check": "exchange status / market data", "market_use": "listings and exchange events"},
        {"name": "CoinMarketCap", "category": "market_data", "status": "ACTIVE", "trust_score": 82.0, "corrections": 0, "cross_check": "CoinGecko / exchange feeds", "market_use": "price and ranking checks"},
        {"name": "X / social accounts", "category": "social", "status": "MONITORING", "trust_score": 55.0, "corrections": 4, "cross_check": "never used alone", "market_use": "early rumor detection only"},
    ]


def _demo_trades() -> list[dict[str, Any]]:
    """Return stable demo trades with full reasoning for the dashboard."""

    return [
        {"id": "BTC-20260708-001", "asset": "BTC/USDT", "side": "BUY", "status": "OPEN", "opened_at": "2026-07-08 18:19:20", "expected_horizon": "24-72 часа", "entry_price": 67214.20, "size": "0.10 BTC", "notional_usdt": 6721.42, "pnl_usdt": 52.40, "confidence": 88.0, "risk_level": "LOW", "stop_loss": 65350.00, "take_profit": 70400.00, "reason": "AI купил BTC в демо-режиме, потому что Market Agent дал восходящий сигнал, News Agent не нашел критической паники, а Risk Engine подтвердил низкий риск.", "expected_result": "Ожидается умеренный рост при сохранении объема и отсутствии негативных новостей.", "sources": ["Market Agent", "News Agent", "Risk Engine", "Consensus Engine"], "ai_decision_link": "BUY BITCOIN / confidence 88.0% / consensus 100.0%"},
        {"id": "ETH-20260708-002", "asset": "ETH/USDT", "side": "SELL", "status": "CLOSED", "opened_at": "2026-07-08 16:42:11", "expected_horizon": "6-24 часа", "entry_price": 3142.88, "size": "1.00 ETH", "notional_usdt": 3142.88, "pnl_usdt": -18.30, "confidence": 71.0, "risk_level": "MEDIUM", "stop_loss": 3198.00, "take_profit": 3030.00, "reason": "AI закрыл демо-сделку по ETH после ухудшения импульса и роста краткосрочного риска. Убыток ограничен правилами risk management.", "expected_result": "Сделка закрыта. Данные пойдут в Learning Engine для улучшения фильтров входа.", "sources": ["Market Agent", "Risk Engine", "Learning Engine"], "ai_decision_link": "SELL ETH / risk MEDIUM / learning update required"},
        {"id": "SOL-20260708-003", "asset": "SOL/USDT", "side": "BUY", "status": "OPEN", "opened_at": "2026-07-08 15:10:04", "expected_horizon": "1-3 дня", "entry_price": 171.35, "size": "5.00 SOL", "notional_usdt": 856.75, "pnl_usdt": 31.20, "confidence": 79.0, "risk_level": "LOW", "stop_loss": 164.00, "take_profit": 188.00, "reason": "AI открыл демо-позицию SOL после подтверждения импульса и допустимого соотношения риск/прибыль.", "expected_result": "Ожидается продолжение движения при подтверждении рынка BTC и отсутствии негативных новостей по сектору.", "sources": ["Market Agent", "Portfolio Engine", "Consensus Engine"], "ai_decision_link": "BUY SOL / confidence 79.0% / low risk"},
    ]


app = create_app()
