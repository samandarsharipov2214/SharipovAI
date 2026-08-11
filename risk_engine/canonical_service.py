"""Canonical production risk service shared by every runtime decision path.

The deterministic :class:`RiskEngine` remains the typed low-level calculator.
This service owns the production policy that combines verified market evidence,
portfolio drawdown, liquidity, consensus, news quality and execution locks. It
never places orders and always keeps real execution disabled.
"""
from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from typing import Any, ClassVar, Mapping

_PROFILES = {"council", "market_regime", "trade_gate", "health_probe"}


@dataclass(frozen=True, slots=True)
class CanonicalRiskAssessment:
    profile: str
    status: str
    decision: str
    allowed_virtual: bool
    allowed_live: bool
    risk_score: float
    risk_level: str
    hard_blocks: tuple[str, ...]
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]
    market_regime: dict[str, Any]
    inputs: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-canonical payload suitable for idempotent persistence."""
        return json.loads(
            json.dumps(
                asdict(self),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
        )


class CanonicalRiskService:
    """Evaluate one normalized risk context through the canonical policy.

    The service is stateless, so all constructors intentionally resolve to the
    same process-local instance. Existing call sites can keep constructing
    ``CanonicalRiskService()`` while Council, Trade Gate and health probes share
    one policy owner rather than silently drifting into separate services.
    """

    service_id = "risk_engine.canonical_service"
    _shared_instance: ClassVar["CanonicalRiskService | None"] = None

    def __new__(cls) -> "CanonicalRiskService":
        if cls._shared_instance is None:
            cls._shared_instance = super().__new__(cls)
        return cls._shared_instance

    def evaluate(
        self,
        payload: Mapping[str, Any] | None = None,
        *,
        profile: str = "council",
    ) -> CanonicalRiskAssessment:
        clean_profile = str(profile).strip().lower()
        if clean_profile not in _PROFILES:
            raise ValueError(f"unsupported canonical risk profile: {profile}")
        values = dict(payload or {})

        market_verified = bool(values.get("market_data_verified", False))
        # Exchange health is independent evidence. Never infer it from a market
        # verification flag supplied by a caller.
        exchange_ok = bool(values.get("exchange_ok", False))
        change = _finite(values.get("price_change_24h_percent", values.get("change_24h_percent", 0.0)))
        volatility = _finite(values.get("volatility_percent", abs(change)))
        trend_score = _finite(values.get("trend_score", max(-1.0, min(1.0, change / 10.0))))
        spread = _finite(values.get("spread_percent", 0.05))
        liquidity_score = _bounded(values.get("liquidity_score", 0.0 if clean_profile == "trade_gate" else 75.0))
        news_shock = _bounded(values.get("news_shock_score", 0.0))
        news_credibility = _bounded(values.get("news_credibility_percent", 0.0 if clean_profile == "trade_gate" else 100.0))
        # Missing Decision Quality evidence must fail closed in the trade gate.
        ai_consensus = _bounded(values.get("ai_consensus_score", 0.0 if clean_profile == "trade_gate" else 100.0))
        risk_per_trade = max(0.0, _finite(values.get("risk_per_trade_percent", 1.0)))
        drawdown = max(0.0, _finite(values.get("portfolio_drawdown_percent", values.get("drawdown_percent", 0.0))))
        deviation = max(0.0, _finite(values.get("ws_consensus_deviation_percent", 0.0)))
        turnover = _optional_finite(values.get("turnover_usdt", values.get("volume_24h")))
        live_requested = bool(values.get("live_requested", False))
        strategy_approved = bool(values.get("strategy_approved", False))

        regime = _market_regime(
            market_verified=market_verified,
            volatility=volatility,
            trend_score=trend_score,
            spread=spread,
            liquidity=liquidity_score,
            news_shock=news_shock,
        )

        hard_blocks: list[str] = []
        blockers: list[str] = []
        warnings: list[str] = []

        if not market_verified:
            _add(
                hard_blocks,
                blockers,
                "market_data_unverified",
                "Актуальная рыночная котировка не подтверждена. Любой вход заблокирован.",
            )
        if not exchange_ok:
            _add(
                hard_blocks,
                blockers,
                "exchange_unavailable",
                "Exchange/API нестабилен, отсутствует или не подтверждён.",
            )

        if clean_profile in {"council", "health_probe"}:
            max_abs_change = max(0.1, _finite(values.get("max_abs_change_percent", 12.0)))
            min_turnover = max(0.0, _finite(values.get("min_turnover_usdt", 5_000_000.0)))
            max_drawdown = max(0.1, _finite(values.get("max_drawdown_percent", 8.0)))
            max_deviation = max(0.0, _finite(values.get("max_consensus_deviation_percent", 0.75)))
            if abs(change) > max_abs_change:
                _add(hard_blocks, blockers, "extreme_24h_volatility", "Суточная волатильность превышает канонический лимит риска.")
            if clean_profile == "council" and turnover is None:
                _add(hard_blocks, blockers, "missing_verified_liquidity", "Подтверждённые данные ликвидности отсутствуют.")
            elif turnover is not None and turnover < min_turnover:
                _add(hard_blocks, blockers, "insufficient_verified_liquidity", "Подтверждённая ликвидность ниже канонического минимума.")
            if drawdown > max_drawdown:
                _add(hard_blocks, blockers, "paper_portfolio_drawdown_limit", "Просадка виртуального портфеля превышает канонический лимит.")
            if deviation > max_deviation:
                _add(hard_blocks, blockers, "websocket_consensus_price_divergence", "Цена WebSocket расходится с межбиржевым консенсусом.")

        if clean_profile == "trade_gate":
            if live_requested:
                _add(
                    hard_blocks,
                    blockers,
                    "live_execution_requested",
                    "REAL/LIVE execution заблокирован: нужен ручной unlock и отдельная проверка безопасности.",
                )
            if regime["recommended_action"] in {"BLOCK", "WAIT"}:
                _add(
                    hard_blocks,
                    blockers,
                    "market_regime_gate",
                    f"Market Regime AI говорит {regime['recommended_action']}: {regime['explanation']}",
                )
            if ai_consensus < 70.0:
                _add(hard_blocks, blockers, "low_ai_consensus", "AI consensus ниже 70% или отсутствует. Сделка не подтверждена.")
            if news_credibility < 65.0:
                _add(hard_blocks, blockers, "low_news_credibility", "Достоверность новостей ниже 65% или отсутствует. Нужна перепроверка.")
            if risk_per_trade > 1.0:
                _add(hard_blocks, blockers, "risk_per_trade_limit", "Риск на сделку выше 1%. Для текущей версии это запрещено.")
            if not strategy_approved:
                warnings.append("Стратегия не прошла полный backtest/virtual-account pipeline. Разрешён только virtual-watch режим.")

        score = _risk_score(
            change=change,
            drawdown=drawdown,
            deviation=deviation,
            hard_blocks=hard_blocks,
        )
        decision = "BLOCK" if blockers else "VIRTUAL_ONLY" if warnings else "VIRTUAL_ALLOWED"
        status = "blocked" if blockers else "ok"
        normalized_inputs = {
            "market_data_verified": market_verified,
            "exchange_ok": exchange_ok,
            "price_change_24h_percent": change,
            "volatility_percent": volatility,
            "trend_score": trend_score,
            "spread_percent": spread,
            "liquidity_score": liquidity_score,
            "news_shock_score": news_shock,
            "news_credibility_percent": news_credibility,
            "ai_consensus_score": ai_consensus,
            "risk_per_trade_percent": risk_per_trade,
            "portfolio_drawdown_percent": drawdown,
            "ws_consensus_deviation_percent": deviation,
            "turnover_usdt": turnover,
            "strategy_approved": strategy_approved,
            "live_requested": live_requested,
        }
        return CanonicalRiskAssessment(
            profile=clean_profile,
            status=status,
            decision=decision,
            allowed_virtual=decision in {"VIRTUAL_ONLY", "VIRTUAL_ALLOWED"},
            allowed_live=False,
            risk_score=score,
            risk_level=_risk_level(score),
            hard_blocks=tuple(dict.fromkeys(hard_blocks)),
            blockers=tuple(dict.fromkeys(blockers)),
            warnings=tuple(dict.fromkeys(warnings)),
            market_regime=regime,
            inputs=normalized_inputs,
        )


def _market_regime(
    *,
    market_verified: bool,
    volatility: float,
    trend_score: float,
    spread: float,
    liquidity: float,
    news_shock: float,
) -> dict[str, Any]:
    if not market_verified:
        regime, risk, action, status = "market_data_unavailable", "high", "BLOCK", "blocked"
    elif news_shock >= 70:
        regime, risk, action, status = "news_shock", "high", "WAIT", "ok"
    elif volatility >= 8:
        regime, risk, action, status = "panic", "high", "BLOCK", "ok"
    elif spread >= 0.25 or liquidity < 35:
        regime, risk, action, status = "bad_execution", "high", "WAIT", "ok"
    elif abs(trend_score) >= 0.65 and volatility < 6:
        regime, risk, action, status = "trend", "medium", "VIRTUAL_ONLY", "ok"
    elif volatility <= 2 and abs(trend_score) < 0.35:
        regime, risk, action, status = "range_low_volatility", "medium", "WAIT", "ok"
    else:
        regime, risk, action, status = "mixed", "medium", "WATCH", "ok"
    return {
        "status": status,
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


def _regime_explanation(regime: str) -> str:
    return {
        "market_data_unavailable": "актуальная котировка не подтверждена; анализ и вход по выдуманной цене запрещены",
        "news_shock": "новостной шок — цена может резко двигаться без технического подтверждения",
        "panic": "паника/высокая волатильность — риск ложных входов и ликвидаций высокий",
        "bad_execution": "плохие условия исполнения — спред/ликвидность могут съесть прибыль",
        "trend": "есть тренд, можно смотреть только виртуальное исполнение при подтверждении риска",
        "range_low_volatility": "боковик/низкая волатильность — лучше ждать сильного сигнала",
        "mixed": "смешанный рынок — нужен дополнительный консенсус AI",
    }.get(regime, "режим неопределён")


def _risk_score(*, change: float, drawdown: float, deviation: float, hard_blocks: list[str]) -> float:
    if hard_blocks:
        return 100.0
    score = 15.0 + min(abs(change) * 3.0, 35.0) + min(drawdown * 4.0, 35.0) + min(deviation * 20.0, 15.0)
    return round(min(max(score, 0.0), 100.0), 6)


def _risk_level(score: float) -> str:
    if score < 30:
        return "LOW"
    if score < 60:
        return "MEDIUM"
    if score < 80:
        return "HIGH"
    return "CRITICAL"


def _add(codes: list[str], messages: list[str], code: str, message: str) -> None:
    codes.append(code)
    messages.append(message)


def _finite(value: Any) -> float:
    if value in (None, "") or isinstance(value, bool):
        raise ValueError("risk numeric input must be a finite number")
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("risk numeric input must be a finite number") from exc
    if not math.isfinite(parsed):
        raise ValueError("risk numeric input must be a finite number")
    return parsed


def _optional_finite(value: Any) -> float | None:
    if value in (None, ""):
        return None
    if isinstance(value, bool):
        raise ValueError("optional risk numeric input must be a finite number")
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("optional risk numeric input must be a finite number") from exc
    if not math.isfinite(parsed):
        raise ValueError("optional risk numeric input must be a finite number")
    return parsed


def _bounded(value: Any) -> float:
    return min(max(_finite(value), 0.0), 100.0)


__all__ = ["CanonicalRiskAssessment", "CanonicalRiskService"]
