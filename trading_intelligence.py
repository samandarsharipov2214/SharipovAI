"""Trading intelligence layer: market regime and strict trade gate.

This is a safety-first layer. It does not place orders. It answers whether the
system is allowed to trade in DEMO, and why LIVE must remain locked.
"""

from __future__ import annotations

from typing import Any

try:
    from news_monitor.analyzer import analyzed_news_payload
except Exception:  # pragma: no cover
    analyzed_news_payload = None  # type: ignore[assignment]


def market_regime(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """Detect simple market regime from optional market payload.

    Expected optional fields: volatility_percent, trend_score, spread_percent,
    news_shock_score, liquidity_score.
    """

    payload = payload or {}
    volatility = float(payload.get("volatility_percent", 2.5) or 0)
    trend_score = float(payload.get("trend_score", 0.2) or 0)
    spread = float(payload.get("spread_percent", 0.05) or 0)
    news_shock = float(payload.get("news_shock_score", _news_shock_score()) or 0)
    liquidity = float(payload.get("liquidity_score", 75) or 0)

    if news_shock >= 70:
        regime = "news_shock"
        risk = "high"
        action = "WAIT"
    elif volatility >= 8:
        regime = "panic"
        risk = "high"
        action = "BLOCK"
    elif spread >= 0.25 or liquidity < 35:
        regime = "bad_execution"
        risk = "high"
        action = "WAIT"
    elif abs(trend_score) >= 0.65 and volatility < 6:
        regime = "trend"
        risk = "medium"
        action = "DEMO_ONLY"
    elif volatility <= 2 and abs(trend_score) < 0.35:
        regime = "range_low_volatility"
        risk = "medium"
        action = "WAIT"
    else:
        regime = "mixed"
        risk = "medium"
        action = "WATCH"

    return {
        "status": "ok",
        "regime": regime,
        "risk_level": risk,
        "recommended_action": action,
        "inputs": {
            "volatility_percent": volatility,
            "trend_score": trend_score,
            "spread_percent": spread,
            "news_shock_score": news_shock,
            "liquidity_score": liquidity,
        },
        "explanation": _regime_explanation(regime),
    }


def trade_gate(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """Strict safety gate: can SharipovAI trade now?"""

    payload = payload or {}
    regime = market_regime(payload)
    live_requested = bool(payload.get("live_requested", False))
    ai_score = float(payload.get("ai_consensus_score", 62) or 0)
    risk_per_trade = float(payload.get("risk_per_trade_percent", 1.0) or 0)
    news_credibility = float(payload.get("news_credibility_percent", _news_credibility()) or 0)
    exchange_ok = bool(payload.get("exchange_ok", True))
    has_strategy_approval = bool(payload.get("strategy_approved", False))

    blockers: list[str] = []
    warnings: list[str] = []

    if live_requested:
        blockers.append("LIVE trading заблокирован: нужен ручной unlock и отдельная проверка безопасности.")
    if regime["recommended_action"] in {"BLOCK", "WAIT"}:
        blockers.append(f"Market Regime AI говорит {regime['recommended_action']}: {regime['explanation']}")
    if ai_score < 70:
        blockers.append("AI consensus ниже 70%. Сделка не подтверждена.")
    if news_credibility < 65:
        blockers.append("Достоверность новостей ниже 65%. Нужна перепроверка.")
    if risk_per_trade > 1.0:
        blockers.append("Риск на сделку выше 1%. Для текущей версии это запрещено.")
    if not exchange_ok:
        blockers.append("Exchange/API нестабилен или не подтверждён.")
    if not has_strategy_approval:
        warnings.append("Стратегия не прошла полный backtest/paper pipeline. Разрешён только demo-watch режим.")

    decision = "BLOCK" if blockers else "DEMO_ONLY" if warnings or not has_strategy_approval else "DEMO_ALLOWED"
    return {
        "status": "ok",
        "decision": decision,
        "can_trade_demo": decision in {"DEMO_ONLY", "DEMO_ALLOWED"},
        "can_trade_live": False,
        "blockers": blockers,
        "warnings": warnings,
        "market_regime": regime,
        "inputs": {
            "ai_consensus_score": ai_score,
            "risk_per_trade_percent": risk_per_trade,
            "news_credibility_percent": news_credibility,
            "exchange_ok": exchange_ok,
            "strategy_approved": has_strategy_approval,
            "live_requested": live_requested,
        },
        "human_answer": _human_answer(decision, blockers, warnings),
    }


def _news_shock_score() -> float:
    if not analyzed_news_payload:
        return 35
    try:
        news = analyzed_news_payload()
        summary = news.get("summary", {}) if isinstance(news, dict) else {}
        urgent = int(summary.get("urgent_count", 0) or 0)
        needs_confirmation = int(summary.get("needs_confirmation", 0) or 0)
        return min(100, urgent * 25 + needs_confirmation * 10)
    except Exception:
        return 35


def _news_credibility() -> float:
    if not analyzed_news_payload:
        return 60
    try:
        news = analyzed_news_payload()
        summary = news.get("summary", {}) if isinstance(news, dict) else {}
        return float(summary.get("average_credibility_percent", 60) or 60)
    except Exception:
        return 60


def _regime_explanation(regime: str) -> str:
    explanations = {
        "news_shock": "новостной шок — цена может резко двигаться без технического подтверждения",
        "panic": "паника/высокая волатильность — риск ложных входов и ликвидаций высокий",
        "bad_execution": "плохие условия исполнения — спред/ликвидность могут съесть прибыль",
        "trend": "есть тренд, можно смотреть только demo при подтверждении риска",
        "range_low_volatility": "боковик/низкая волатильность — лучше ждать сильного сигнала",
        "mixed": "смешанный рынок — нужен дополнительный консенсус AI",
    }
    return explanations.get(regime, "режим неопределён")


def _human_answer(decision: str, blockers: list[str], warnings: list[str]) -> str:
    if decision == "BLOCK":
        return "НЕТ. Торговать нельзя. " + " ".join(blockers[:3])
    if decision == "DEMO_ONLY":
        return "ТОЛЬКО DEMO. LIVE запрещён. " + " ".join(warnings[:2])
    return "Можно только DEMO при сохранении лимитов риска. LIVE всё равно запрещён."
