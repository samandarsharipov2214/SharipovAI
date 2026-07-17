"""Trading intelligence layer: verified market regime and strict trade gate.

This safety-first layer never places real orders. When no explicit payload is
provided it reads a verified public quote through exchange_connector.market_data.
If current market data cannot be verified, virtual and live entries are blocked.
"""
from __future__ import annotations

from typing import Any

from exchange_connector.market_data import MarketDataService, MarketDataUnavailable

try:
    from news_monitor.analyzer import analyzed_news_payload
except Exception:  # pragma: no cover
    analyzed_news_payload = None  # type: ignore[assignment]

_MARKET_DATA = MarketDataService()


def verified_market_payload(symbol: str = "BTCUSDT") -> dict[str, Any]:
    """Return normalized live inputs with provenance for downstream safety gates."""
    quote = _MARKET_DATA.quote(symbol)
    change = float(quote.change_24h_percent or 0.0)
    volume = float(quote.volume_24h or 0.0)
    return {
        "symbol": quote.symbol,
        "market_data_verified": quote.verified,
        "exchange_ok": quote.verified,
        "price": quote.price,
        "price_change_24h_percent": change,
        "volatility_percent": abs(change),
        "trend_score": max(-1.0, min(1.0, change / 10.0)),
        "liquidity_score": 80.0 if volume > 0 else 35.0,
        "market_quote": quote.to_dict(),
    }


def _resolved_payload(payload: dict[str, Any] | None) -> tuple[dict[str, Any], str | None]:
    if payload is not None:
        result = dict(payload)
        # Exchange availability is not proof that the exact market observation is
        # verified. Explicit evidence is required for every virtual or Testnet entry.
        result.setdefault("market_data_verified", False)
        return result, None
    try:
        return verified_market_payload(), None
    except MarketDataUnavailable as exc:
        return {
            "market_data_verified": False,
            "exchange_ok": False,
            "symbol": "BTCUSDT",
        }, str(exc)


def market_regime(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """Detect market regime from verified live data or an explicit test payload."""
    payload, market_error = _resolved_payload(payload)
    if not bool(payload.get("market_data_verified", False)):
        return {
            "status": "blocked",
            "regime": "market_data_unavailable",
            "risk_level": "high",
            "recommended_action": "BLOCK",
            "inputs": payload,
            "market_data_error": market_error,
            "explanation": "актуальная котировка не подтверждена; анализ и вход по выдуманной цене запрещены",
        }

    volatility = float(payload.get("volatility_percent", 0.0) or 0)
    trend_score = float(payload.get("trend_score", 0.0) or 0)
    spread = float(payload.get("spread_percent", 0.05) or 0)
    raw_news_shock = payload.get("news_shock_score")
    news_shock = float(_news_shock_score() if raw_news_shock is None else raw_news_shock or 0)
    liquidity = float(payload.get("liquidity_score", 75) or 0)

    if news_shock >= 70:
        regime, risk, action = "news_shock", "high", "WAIT"
    elif volatility >= 8:
        regime, risk, action = "panic", "high", "BLOCK"
    elif spread >= 0.25 or liquidity < 35:
        regime, risk, action = "bad_execution", "high", "WAIT"
    elif abs(trend_score) >= 0.65 and volatility < 6:
        regime, risk, action = "trend", "medium", "VIRTUAL_ONLY"
    elif volatility <= 2 and abs(trend_score) < 0.35:
        regime, risk, action = "range_low_volatility", "medium", "WAIT"
    else:
        regime, risk, action = "mixed", "medium", "WATCH"

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
        "market_quote": payload.get("market_quote"),
        "explanation": _regime_explanation(regime),
    }


def trade_gate(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """Strict gate for virtual execution; real execution always remains locked."""
    resolved, market_error = _resolved_payload(payload)

    if "news_shock_score" not in resolved or "news_credibility_percent" not in resolved:
        default_shock, default_credibility = _news_metrics()
        resolved.setdefault("news_shock_score", default_shock)
        resolved.setdefault("news_credibility_percent", default_credibility)

    regime = market_regime(resolved)
    live_requested = bool(resolved.get("live_requested", False))
    ai_score = float(resolved.get("ai_consensus_score", 62) or 0)
    risk_per_trade = float(resolved.get("risk_per_trade_percent", 1.0) or 0)
    news_credibility = float(resolved.get("news_credibility_percent", 60) or 0)
    exchange_ok = bool(resolved.get("exchange_ok", False))
    market_verified = bool(resolved.get("market_data_verified", False))
    has_strategy_approval = bool(resolved.get("strategy_approved", False))

    blockers: list[str] = []
    warnings: list[str] = []
    if not market_verified:
        blockers.append("Актуальная рыночная котировка не подтверждена. Любой вход заблокирован.")
    if live_requested:
        blockers.append("REAL/LIVE execution заблокирован: нужен ручной unlock и отдельная проверка безопасности.")
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
        warnings.append("Стратегия не прошла полный backtest/virtual-account pipeline. Разрешён только virtual-watch режим.")

    decision = "BLOCK" if blockers else "VIRTUAL_ONLY" if warnings else "VIRTUAL_ALLOWED"
    return {
        "status": "ok" if market_verified else "blocked",
        "decision": decision,
        "can_trade_virtual": decision in {"VIRTUAL_ONLY", "VIRTUAL_ALLOWED"},
        "can_trade_demo": decision in {"VIRTUAL_ONLY", "VIRTUAL_ALLOWED"},
        "can_trade_live": False,
        "can_trade_real": False,
        "market_data_verified": market_verified,
        "market_data_error": market_error,
        "market_quote": resolved.get("market_quote"),
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


def _news_metrics() -> tuple[float, float]:
    """Read news once and derive all gate metrics from the same snapshot."""
    if not analyzed_news_payload:
        return 35.0, 60.0
    try:
        news = analyzed_news_payload()
        summary = news.get("summary", {}) if isinstance(news, dict) else {}
        shock = min(
            100,
            int(summary.get("urgent_count", 0) or 0) * 25
            + int(summary.get("needs_confirmation", 0) or 0) * 10,
        )
        credibility = float(summary.get("average_credibility_percent", 60) or 60)
        return float(shock), credibility
    except Exception:
        return 35.0, 60.0


def _news_shock_score() -> float:
    shock, _ = _news_metrics()
    return shock


def _news_credibility() -> float:
    _, credibility = _news_metrics()
    return credibility


def _regime_explanation(regime: str) -> str:
    explanations = {
        "news_shock": "новостной шок — цена может резко двигаться без технического подтверждения",
        "panic": "паника/высокая волатильность — риск ложных входов и ликвидаций высокий",
        "bad_execution": "плохие условия исполнения — спред/ликвидность могут съесть прибыль",
        "trend": "есть тренд, можно смотреть только виртуальное исполнение при подтверждении риска",
        "range_low_volatility": "боковик/низкая волатильность — лучше ждать сильного сигнала",
        "mixed": "смешанный рынок — нужен дополнительный консенсус AI",
    }
    return explanations.get(regime, "режим неопределён")


def _human_answer(decision: str, blockers: list[str], warnings: list[str]) -> str:
    if decision == "BLOCK":
        return "НЕТ. Реальную сделку и виртуальный вход нельзя открывать. " + " ".join(blockers[:3])
    if decision == "VIRTUAL_ONLY":
        return "ТОЛЬКО ВИРТУАЛЬНЫЙ СЧЁТ. Реальное исполнение запрещено. " + " ".join(warnings[:2])
    return "Можно только на виртуальном счёте при сохранении лимитов риска. Реальное исполнение всё равно запрещено."
