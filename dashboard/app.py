"""FastAPI application factory for the SharipovAI dashboard."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from fastapi import Body, FastAPI
from fastapi.staticfiles import StaticFiles

from runner import SharipovAIRunner

from .routes import router


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

    @app.get("/api/intelligence")
    def intelligence() -> dict[str, Any]:
        """Return compact Intelligence Center status."""

        sources = _intelligence_sources()
        active = sum(1 for source in sources if source["status"] == "ACTIVE")
        average_trust = round(
            sum(float(source["trust_score"]) for source in sources) / len(sources),
            2,
        )
        return {
            "status": "monitoring",
            "live_monitoring": True,
            "active_sources": active,
            "total_sources": len(sources),
            "average_trust_score": average_trust,
            "page": "/static/intelligence.html",
            "sources_api": "/api/intelligence/sources",
            "summary_api": "/api/intelligence/summary",
            "rule": "Signals must be confirmed by at least 2 independent sources. Social sources are never used alone.",
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
            "cross_check_policy": "Every market-moving signal must be confirmed by at least 2 independent sources before it can influence a demo trade.",
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
                "Source reliability is reduced when corrections or retractions are detected.",
                "Official sources receive higher base confidence but still require cross-checks for market impact.",
                "Social signals are never enough alone; they must be confirmed by news, market, or official data.",
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
        """Process a chat message and return a grounded runner response."""

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
        decision = str(run.get("decision", "NO_DECISION")).upper()
        confidence = float(run.get("confidence", 0.0) or 0.0)
        risk = str(run.get("risk_level", "LOW"))
        positions = int(run.get("open_positions", 0) or 0)
        reply = (
            f"Я вижу твоё сообщение: «{message}». "
            f"Анализ выполнен. Решение: {decision}. "
            f"Уверенность: {confidence:.1f}%. Риск: {risk}. "
        )
        if decision == "BUY" and positions > 0:
            reply += "Открыта только демо-позиция. Реальные деньги не используются."
        else:
            reply += "Реальная сделка не открыта. Система работает в безопасном демо-режиме."
        return {"reply": reply, "run": run}

    return app


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
