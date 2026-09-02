"""Autonomous, fail-closed council proposal provider.

The provider continuously turns verified market, news, liquidity, portfolio and
canonical risk evidence into independent agent opinions. Missing or weak
evidence produces WAIT; the canonical Risk Engine remains the only financial
veto owner in this layer.
"""
from __future__ import annotations

import math
import os
import time
from collections.abc import Callable, Mapping
from typing import Any

from news_monitor.agent_network import agent_detail
from risk_engine import CanonicalRiskService
from storage import ProjectDatabase, ProjectDomainStore
from trading_candidate import (
    MarketRegime,
    TradingCategory,
    TradingDecision,
    TradingEnvironment,
    TradingSide,
)

from decision_quality import CandidateEvidencePacket
from .council_loop import CouncilEntryProposal


_NEWS_AGENTS = ("crypto_ai", "finance_ai", "economy_ai", "security_ai", "world_ai")
_POSITIVE = {"positive", "bullish", "up", "growth", "supportive", "risk_on"}
_NEGATIVE = {"negative", "bearish", "down", "decline", "adverse", "risk_off"}
_MAX_MARKET_AGE_MS = 2_000
_DEFAULT_RISK_SERVICE = CanonicalRiskService()


class AutonomousCouncilProposalProvider:
    """Create one traceable proposal per fresh market observation window."""

    def __init__(
        self,
        database: ProjectDatabase,
        stream: Any,
        *,
        news_reader: Callable[..., Mapping[str, Any]] | None = None,
        risk_service: CanonicalRiskService | None = None,
    ) -> None:
        self.database = database
        self.database.initialize()
        self.store = ProjectDomainStore(database)
        self.stream = stream
        self.news_reader = news_reader or agent_detail
        self.risk_service = risk_service or CanonicalRiskService()
        self.proposal_interval_ms = int(
            min(max(float(os.getenv("COUNCIL_PROPOSAL_INTERVAL_SECONDS", "60")), 10.0), 900.0) * 1000
        )
        self.news_max_age_seconds = int(
            min(max(float(os.getenv("COUNCIL_NEWS_MAX_AGE_SECONDS", "21600")), 300.0), 172800.0)
        )
        self.entry_change_percent = min(
            max(float(os.getenv("COUNCIL_ENTRY_CHANGE_PERCENT", "0.8")), 0.2),
            8.0,
        )
        self.max_abs_change_percent = min(
            max(float(os.getenv("COUNCIL_MAX_ABS_CHANGE_PERCENT", "12")), 3.0),
            30.0,
        )
        self.min_turnover_usdt = min(
            max(float(os.getenv("COUNCIL_MIN_TURNOVER_USDT", "5000000")), 100000.0),
            1_000_000_000.0,
        )
        self.max_drawdown_percent = min(
            max(float(os.getenv("COUNCIL_MAX_PAPER_DRAWDOWN_PERCENT", "8")), 1.0),
            25.0,
        )
        self.fee_percent = min(max(float(os.getenv("EXCHANGE_DEFAULT_FEE_RATE", "0.001")) * 100, 0.0), 5.0)
        self.slippage_percent = min(
            max(float(os.getenv("COUNCIL_ESTIMATED_SLIPPAGE_PERCENT", "0.05")), 0.0),
            2.0,
        )
        self._last_market_evidence: dict[str, dict[str, Any]] = {}

    def __call__(self, symbol: str, quote: Any, state: Mapping[str, Any]) -> CouncilEntryProposal | None:
        now_ms = int(time.time() * 1000)
        clean_symbol = _symbol(symbol)
        last = self.database.get_json("autonomous_council_runtime", clean_symbol)
        if last is not None:
            generated = int(last["value"].get("last_generated_at_ms") or 0)
            if now_ms - generated < self.proposal_interval_ms:
                return None

        market = self.stream.evidence(clean_symbol)
        self._last_market_evidence[clean_symbol] = dict(market) if isinstance(market, Mapping) else {}
        if market.get("verified") is not True or market.get("synthetic_fallback_used") is True:
            return None
        sources = tuple(str(item) for item in market.get("consensus_sources", ()) if str(item).strip())
        if len(set(sources)) < 3:
            return None

        change = _finite_or_none(getattr(quote, "change_24h_percent", None))
        turnover = _finite_or_none(getattr(quote, "volume_24h", None))
        if change is None or turnover is None or turnover < 0:
            return None
        market_timestamp_ms = int(getattr(quote, "received_at_unix_ms", 0) or 0)
        if market_timestamp_ms <= 0 or now_ms - market_timestamp_ms > _MAX_MARKET_AGE_MS:
            return None

        decision_id = f"paper-{clean_symbol}-{market_timestamp_ms}"
        market_action = _direction(change, self.entry_change_percent)
        regime = _market_regime(change, turnover, self.min_turnover_usdt)
        drawdown_percent = _drawdown_percent(state)
        risk_assessment = self.risk_service.evaluate(
            {
                "market_data_verified": True,
                "exchange_ok": True,
                "price_change_24h_percent": change,
                "volatility_percent": abs(change),
                "turnover_usdt": turnover,
                "liquidity_score": 80.0 if turnover >= self.min_turnover_usdt else 0.0,
                "portfolio_drawdown_percent": drawdown_percent,
                "open_position_count": _open_position_count(state),
                "ws_consensus_deviation_percent": float(market.get("ws_consensus_deviation_percent") or 0.0),
                "max_abs_change_percent": self.max_abs_change_percent,
                "min_turnover_usdt": self.min_turnover_usdt,
                "max_drawdown_percent": self.max_drawdown_percent,
                "max_consensus_deviation_percent": 0.75,
                "live_requested": False,
            },
            profile="council",
        )
        risk_blocks = tuple(risk_assessment.hard_blocks)
        risk_score = float(risk_assessment.risk_score)

        opinions: list[dict[str, Any]] = [
            _opinion(
                "market_intelligence",
                market_action,
                70.0 + min(abs(change) * 5.0, 24.0),
                96.0,
                risk_score,
                f"verified 24h change={change:.4f}% from shared Bybit stream",
            ),
            _opinion(
                "cross_exchange_validation",
                market_action,
                82.0 + min(len(sources), 5) * 2.0,
                98.0,
                min(risk_score, 35.0),
                f"{len(sources)} independent exchanges agree; max deviation="
                f"{float(market.get('consensus_maximum_deviation_percent') or 0.0):.6f}%",
            ),
            _opinion(
                "liquidity_intelligence",
                "BUY" if market_action == "BUY" and turnover >= self.min_turnover_usdt else "WAIT",
                82.0 if turnover >= self.min_turnover_usdt else 55.0,
                92.0,
                15.0 if turnover >= self.min_turnover_usdt else 75.0,
                f"verified 24h turnover={turnover:.2f} USDT",
            ),
            _portfolio_opinion(state, market_action),
        ]

        news_evidence: list[str] = []
        for agent_id in _NEWS_AGENTS:
            payload, evidence_ids = self._news_opinion(agent_id, now_ms=now_ms)
            if payload is not None:
                opinions.append(payload)
                news_evidence.extend(evidence_ids)

        if risk_blocks:
            opinions.append(
                _opinion(
                    "risk_engine",
                    "BLOCK",
                    100.0,
                    100.0,
                    100.0,
                    "; ".join(risk_blocks),
                )
            )
        else:
            recovery = [
                item
                for item in risk_assessment.warnings
                if str(item).startswith("paper_flat_drawdown_recovery")
            ]
            opinions.append(
                _opinion(
                    "risk_engine",
                    "WAIT",
                    35.0,
                    98.0,
                    risk_score,
                    recovery[0]
                    if recovery
                    else "canonical risk checks passed; Risk Engine does not create direction",
                )
            )

        # News/risk evidence construction performs bounded synchronous reads.
        # Recheck the exact quote before persisting a candidate so slow I/O can
        # never turn a previously fresh observation into a stale proposal.
        if int(time.time() * 1000) - market_timestamp_ms > _MAX_MARKET_AGE_MS:
            return None

        eligible = [item for item in opinions if item.get("evidence_eligible") is not False]
        if len(eligible) < 4:
            return None
        directive = _general_controller_directive(eligible, risk_blocks=risk_blocks, state=state)
        side = TradingSide.SELL if market_action == "SELL" else TradingSide.BUY

        portfolio_id = f"portfolio-{decision_id}"
        cost_id = f"cost-{decision_id}"
        news_id = f"news-{decision_id}"
        market_id = f"market-{decision_id}"
        risk_id = f"risk-{decision_id}"
        self._put_once("council_market_evidence", market_id, {**market, "decision_id": decision_id})
        self._put_once(
            "council_news_assessments",
            news_id,
            {
                "decision_id": decision_id,
                "evidence_ids": sorted(set(news_evidence)),
                "agents": [item["agent_id"] for item in opinions if item["agent_id"] in _NEWS_AGENTS],
                "verified_market_data": True,
            },
        )
        self._put_once(
            "portfolio_snapshots",
            portfolio_id,
            {
                "decision_id": decision_id,
                "cash": _finite(state.get("cash", 0.0), "cash"),
                "equity": _finite(state.get("equity", 0.0), "equity"),
                "open_symbols": list(state.get("open_symbols", ())),
                "captured_at_ms": now_ms,
                "environment": "paper",
            },
        )
        self._put_once(
            "cost_snapshots",
            cost_id,
            {
                "decision_id": decision_id,
                "estimated_fee_percent": self.fee_percent,
                "estimated_slippage_percent": self.slippage_percent,
                "captured_at_ms": now_ms,
            },
        )
        self._put_once(
            "risk_assessments",
            risk_id,
            {
                "decision_id": decision_id,
                "risk_score": risk_score,
                "risk_level": risk_assessment.risk_level,
                "blocks": list(risk_blocks),
                "drawdown_percent": drawdown_percent,
                "captured_at_ms": now_ms,
                "canonical_service": self.risk_service.service_id,
                "assessment": risk_assessment.to_dict(),
            },
        )

        # Evidence writes are separate fail-closed transactions. Guard the
        # remaining bridge window as well; immutable evidence may remain as an
        # audit of the abandoned attempt, but it cannot authorize PAPER.
        if int(time.time() * 1000) - market_timestamp_ms > _MAX_MARKET_AGE_MS:
            return None

        packet = CandidateEvidencePacket(
            candidate_id=decision_id,
            symbol=clean_symbol,
            category=TradingCategory.SPOT,
            side=side,
            environment=TradingEnvironment.PAPER,
            market_timestamp_ms=market_timestamp_ms,
            received_timestamp_ms=now_ms,
            reference_price=_positive(getattr(quote, "price", None), "reference_price"),
            data_sources=tuple(dict.fromkeys(sources)),
            market_regime=regime,
            signal_evidence=(market_id, risk_id, portfolio_id, cost_id),
            news_evidence=tuple(sorted(set(news_evidence))),
            news_assessment_id=news_id,
            portfolio_snapshot_id=portfolio_id,
            cost_snapshot_id=cost_id,
            estimated_fees=self.fee_percent,
            estimated_slippage=self.slippage_percent,
            risk_score=risk_score,
            risk_blocks=tuple(risk_blocks),
            expires_at_ms=now_ms + 8_000,
        )
        self.database.put_json(
            "autonomous_council_runtime",
            clean_symbol,
            {
                "last_generated_at_ms": now_ms,
                "last_decision_id": decision_id,
                "general_controller_decision": directive.value,
                "market_action": market_action,
                "agent_count": len(eligible),
                "news_evidence_count": len(set(news_evidence)),
                "risk_blocks": list(risk_blocks),
                "canonical_risk_service": self.risk_service.service_id,
            },
        )
        return CouncilEntryProposal(
            decision_id=decision_id,
            agent_payloads=tuple(eligible),
            evidence_packet=packet,
            general_controller_decision=directive,
            regime=_meta_regime(regime),
        )

    def last_market_evidence(self, symbol: str) -> dict[str, Any]:
        """Return the exact evidence snapshot consumed by the latest provider call."""
        return dict(self._last_market_evidence.get(_symbol(symbol), {}))

    def _news_opinion(self, agent_id: str, *, now_ms: int) -> tuple[dict[str, Any] | None, list[str]]:
        try:
            detail = self.news_reader(agent_id, run_now=False)
        except TypeError:
            detail = self.news_reader(agent_id)
        except Exception:
            return None, []
        if not isinstance(detail, Mapping) or detail.get("status") not in {"ok", "warning"}:
            return None, []
        agent = detail.get("agent") if isinstance(detail.get("agent"), Mapping) else {}
        if str(agent.get("status", "")).lower() != "active":
            return None, []
        cutoff = now_ms // 1000 - self.news_max_age_seconds
        memories = [
            item
            for item in detail.get("memory", ())
            if isinstance(item, Mapping) and int(item.get("created_at") or 0) >= cutoff
        ]
        if not memories:
            return None, []
        signed: list[float] = []
        credibility: list[float] = []
        confirmations = 0
        evidence_ids: list[str] = []
        for item in memories[-50:]:
            impact = str(item.get("impact") or "neutral").strip().lower()
            raw_score = _finite_or_none(item.get("impact_score")) or 0.0
            magnitude = min(abs(raw_score), 100.0)
            if impact in _NEGATIVE or raw_score < 0:
                signed.append(-magnitude)
            elif impact in _POSITIVE or raw_score > 0:
                signed.append(magnitude)
            else:
                signed.append(0.0)
            credibility.append(min(max(_finite_or_none(item.get("credibility_percent")) or 0.0, 0.0), 100.0))
            confirmations += int(bool(item.get("needs_confirmation")))
            key = str(item.get("key") or "").strip()
            if key:
                evidence_ids.append(key)
        average = sum(signed) / len(signed)
        average_credibility = sum(credibility) / len(credibility)
        action = "BUY" if average >= 8.0 else "SELL" if average <= -8.0 else "WAIT"
        confidence = min(95.0, 55.0 + abs(average) * 0.6)
        confirmation_ratio = confirmations / len(memories)
        evidence_score = max(35.0, average_credibility * (1.0 - confirmation_ratio * 0.5))
        risk = min(85.0, 20.0 + confirmation_ratio * 60.0 + (15.0 if action == "SELL" else 0.0))
        return (
            _opinion(
                agent_id,
                action,
                confidence,
                evidence_score,
                risk,
                f"{len(memories)} fresh verified news memories; signed impact={average:.3f}",
            ),
            evidence_ids,
        )

    def _put_once(self, namespace: str, key: str, value: Mapping[str, Any]) -> None:
        existing = self.database.get_json(namespace, key)
        if existing is not None:
            if existing.get("value") != dict(value):
                raise RuntimeError(f"immutable evidence collision: {namespace}/{key}")
            return
        self.database.put_json(namespace, key, dict(value), expected_version=0)


def _opinion(
    agent_id: str,
    action: str,
    confidence: float,
    evidence_score: float,
    risk_score: float,
    rationale: str,
) -> dict[str, Any]:
    return {
        "agent_id": agent_id,
        "action": action,
        "confidence": _bounded(confidence),
        "evidence_score": _bounded(evidence_score),
        "risk_score": _bounded(risk_score),
        "rationale": rationale[:2_000],
        "evidence_class": "verified_market",
        "verified_market_data": True,
        "learning_eligible": True,
        "evidence_eligible": True,
        "reputation_eligible": True,
    }


def _portfolio_opinion(state: Mapping[str, Any], market_action: str) -> dict[str, Any]:
    cash = max(_finite(state.get("cash", 0.0), "cash"), 0.0)
    equity = max(_finite(state.get("equity", 0.0), "equity"), 0.0)
    open_symbols = tuple(state.get("open_symbols", ()))
    cash_ratio = cash / equity if equity > 0 else 0.0
    action = "BUY" if market_action == "BUY" and cash_ratio >= 0.25 and not open_symbols else "WAIT"
    return _opinion(
        "portfolio_engine",
        action,
        78.0 if action == "BUY" else 60.0,
        95.0,
        20.0 if cash_ratio >= 0.25 else 70.0,
        f"cash ratio={cash_ratio:.4f}; open symbols={len(open_symbols)}",
    )


def _general_controller_directive(
    opinions: list[Mapping[str, Any]],
    *,
    risk_blocks: tuple[str, ...],
    state: Mapping[str, Any],
) -> TradingDecision:
    if risk_blocks:
        return TradingDecision.BLOCK
    buy = [item for item in opinions if item.get("action") == "BUY" and item.get("agent_id") != "risk_engine"]
    sell = [item for item in opinions if item.get("action") == "SELL"]
    news_buy = any(item.get("agent_id") in _NEWS_AGENTS and item.get("action") == "BUY" for item in opinions)
    cash = _finite(state.get("cash", 0.0), "cash")
    if len(buy) >= 4 and not sell and news_buy and cash > 0:
        return TradingDecision.ALLOW
    return TradingDecision.WAIT


def _risk_blocks(
    *,
    change: float,
    turnover: float,
    drawdown_percent: float,
    max_abs_change: float,
    min_turnover: float,
    max_drawdown: float,
    deviation: float,
    open_position_count: int | None = None,
) -> tuple[str, ...]:
    """Backward-compatible wrapper over the canonical Risk Engine service."""
    payload: dict[str, Any] = {
        "market_data_verified": True,
        "exchange_ok": True,
        "price_change_24h_percent": change,
        "turnover_usdt": turnover,
        "portfolio_drawdown_percent": drawdown_percent,
        "ws_consensus_deviation_percent": deviation,
        "max_abs_change_percent": max_abs_change,
        "min_turnover_usdt": min_turnover,
        "max_drawdown_percent": max_drawdown,
    }
    if open_position_count is not None:
        payload["open_position_count"] = open_position_count
    assessment = _DEFAULT_RISK_SERVICE.evaluate(payload, profile="council")
    return tuple(assessment.hard_blocks)


def _risk_score(change: float, drawdown: float, market: Mapping[str, Any], blocks: tuple[str, ...]) -> float:
    """Backward-compatible score wrapper; ``blocks`` cannot weaken the service."""
    assessment = _DEFAULT_RISK_SERVICE.evaluate(
        {
            "market_data_verified": True,
            "exchange_ok": True,
            "price_change_24h_percent": change,
            "portfolio_drawdown_percent": drawdown,
            "ws_consensus_deviation_percent": float(market.get("ws_consensus_deviation_percent") or 0.0),
            "max_abs_change_percent": 0.0 if blocks else 1_000_000.0,
        },
        profile="council",
    )
    return 100.0 if blocks else float(assessment.risk_score)


def _market_regime(change: float, turnover: float, min_turnover: float) -> MarketRegime:
    if turnover < min_turnover:
        return MarketRegime.ILLIQUID
    if abs(change) >= 8.0:
        return MarketRegime.HIGH_VOLATILITY
    if abs(change) >= 0.5:
        return MarketRegime.TREND
    return MarketRegime.RANGE


def _meta_regime(regime: MarketRegime) -> str:
    return {
        MarketRegime.TREND: "bull",
        MarketRegime.RANGE: "sideways",
        MarketRegime.HIGH_VOLATILITY: "high_volatility",
        MarketRegime.ILLIQUID: "unknown",
        MarketRegime.UNKNOWN: "unknown",
    }[regime]


def _direction(change: float, threshold: float) -> str:
    if change >= threshold:
        return "BUY"
    if change <= -threshold:
        return "SELL"
    return "WAIT"


def _open_position_count(state: Mapping[str, Any]) -> int | None:
    open_symbols = state.get("open_symbols")
    if open_symbols is not None:
        if isinstance(open_symbols, (list, tuple, set)):
            return len(open_symbols)
        return None
    positions = state.get("positions")
    if isinstance(positions, dict):
        return len(positions)
    return None


def _drawdown_percent(state: Mapping[str, Any]) -> float:
    equity = max(_finite(state.get("equity", 0.0), "equity"), 0.0)
    peak = max(_finite(state.get("peak_equity", equity), "peak_equity"), equity)
    if peak <= 0:
        return 100.0
    return max(0.0, (peak - equity) / peak * 100.0)


def _symbol(value: Any) -> str:
    clean = str(value or "").strip().upper().replace("/", "").replace("-", "")
    if not clean or not clean.isalnum() or len(clean) > 30:
        raise ValueError("invalid symbol")
    return clean


def _positive(value: Any, field: str) -> float:
    parsed = _finite(value, field)
    if parsed <= 0:
        raise ValueError(f"{field} must be positive")
    return parsed


def _finite(value: Any, field: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{field} must be finite")
    parsed = float(value)
    if not math.isfinite(parsed):
        raise ValueError(f"{field} must be finite")
    return parsed


def _finite_or_none(value: Any) -> float | None:
    if value in (None, "") or isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _bounded(value: float) -> float:
    return round(min(max(float(value), 0.0), 100.0), 6)


__all__ = ["AutonomousCouncilProposalProvider"]
