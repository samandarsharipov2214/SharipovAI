"""Trading intelligence layer backed by the canonical Risk Engine service.

This safety-first layer never places real orders. When no explicit payload is
provided it reads a verified public quote through exchange_connector.market_data.
If current market data cannot be verified, virtual and live entries are blocked.
"""
from __future__ import annotations

from typing import Any

from exchange_connector.market_data import MarketDataService, MarketDataUnavailable
from risk_engine import CanonicalRiskService

try:
    from news_monitor.analyzer import analyzed_news_payload
except Exception:  # pragma: no cover
    analyzed_news_payload = None  # type: ignore[assignment]

_MARKET_DATA = MarketDataService()
_RISK = CanonicalRiskService()


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
        "turnover_usdt": volume,
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
    """Detect market regime through the same service used by council and gate."""
    resolved, market_error = _resolved_payload(payload)
    if "news_shock_score" not in resolved:
        resolved["news_shock_score"] = _news_shock_score()
    assessment = _RISK.evaluate(resolved, profile="market_regime")
    regime = dict(assessment.market_regime)
    regime["market_quote"] = resolved.get("market_quote")
    regime["market_data_error"] = market_error
    regime["canonical_risk_service"] = _RISK.service_id
    return regime


def trade_gate(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """Strict gate for virtual execution; real execution always remains locked."""
    resolved, market_error = _resolved_payload(payload)

    if "news_shock_score" not in resolved or "news_credibility_percent" not in resolved:
        default_shock, default_credibility = _news_metrics()
        resolved.setdefault("news_shock_score", default_shock)
        resolved.setdefault("news_credibility_percent", default_credibility)

    assessment = _RISK.evaluate(resolved, profile="trade_gate")
    blockers = list(assessment.blockers)
    warnings = list(assessment.warnings)
    regime = dict(assessment.market_regime)
    regime["market_quote"] = resolved.get("market_quote")
    regime["market_data_error"] = market_error

    return {
        "status": assessment.status,
        "decision": assessment.decision,
        "can_trade_virtual": assessment.allowed_virtual,
        "can_trade_demo": assessment.allowed_virtual,
        "can_trade_live": False,
        "can_trade_real": False,
        "market_data_verified": assessment.inputs["market_data_verified"],
        "market_data_error": market_error,
        "market_quote": resolved.get("market_quote"),
        "blockers": blockers,
        "warnings": warnings,
        "market_regime": regime,
        "inputs": {
            "ai_consensus_score": assessment.inputs["ai_consensus_score"],
            "risk_per_trade_percent": assessment.inputs["risk_per_trade_percent"],
            "news_credibility_percent": assessment.inputs["news_credibility_percent"],
            "exchange_ok": assessment.inputs["exchange_ok"],
            "strategy_approved": assessment.inputs["strategy_approved"],
            "live_requested": assessment.inputs["live_requested"],
        },
        "risk_assessment": assessment.to_dict(),
        "canonical_risk_service": _RISK.service_id,
        "human_answer": _human_answer(assessment.decision, blockers, warnings),
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
    """Compatibility wrapper over the canonical service's explanation."""
    assessment = _RISK.evaluate(
        {
            "market_data_verified": True,
            "exchange_ok": True,
            "volatility_percent": 0.0,
            "trend_score": 0.0,
            "liquidity_score": 75.0,
            "news_shock_score": 0.0,
        },
        profile="market_regime",
    )
    if assessment.market_regime.get("regime") == regime:
        return str(assessment.market_regime.get("explanation", "режим неопределён"))
    return {
        "market_data_unavailable": "актуальная котировка не подтверждена; анализ и вход по выдуманной цене запрещены",
        "news_shock": "новостной шок — цена может резко двигаться без технического подтверждения",
        "panic": "паника/высокая волатильность — риск ложных входов и ликвидаций высокий",
        "bad_execution": "плохие условия исполнения — спред/ликвидность могут съесть прибыль",
        "trend": "есть тренд, можно смотреть только виртуальное исполнение при подтверждении риска",
        "range_low_volatility": "боковик/низкая волатильность — лучше ждать сильного сигнала",
        "mixed": "смешанный рынок — нужен дополнительный консенсус AI",
    }.get(regime, "режим неопределён")


def _human_answer(decision: str, blockers: list[str], warnings: list[str]) -> str:
    if decision == "BLOCK":
        return "НЕТ. Реальную сделку и виртуальный вход нельзя открывать. " + " ".join(blockers[:3])
    if decision == "VIRTUAL_ONLY":
        return "ТОЛЬКО ВИРТУАЛЬНЫЙ СЧЁТ. Реальное исполнение запрещено. " + " ".join(warnings[:2])
    return "Можно только на виртуальном счёте при сохранении лимитов риска. Реальное исполнение всё равно запрещено."
