"""Shadow-only General Controller V2 decision contract.

General Controller is the owner of the final trading direction. Specialist
agents provide evidence and recommendations; Decision Quality assesses the
quality of that evidence; Risk, Portfolio and Security are mandatory gates.

This first migration slice is deliberately non-executing. It can calculate and
persist/compare shadow decisions, but ``execution_authority`` is always False.
Existing paper execution remains authoritative until a later, separately
reviewed migration explicitly switches authority.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
from math import isfinite
from typing import Iterable


class TradingIntent(StrEnum):
    BUY = "BUY"
    SELL = "SELL"
    WAIT = "WAIT"


class GateVerdict(StrEnum):
    PASS = "PASS"
    WAIT = "WAIT"
    BLOCK = "BLOCK"


_NON_DIRECTIONAL_AGENTS = frozenset(
    {
        "decision_quality",
        "portfolio_engine",
        "risk_engine",
        "security_guard",
    }
)
_REQUIRED_GATES = ("risk_engine", "portfolio_engine", "security_guard")


@dataclass(frozen=True, slots=True)
class SpecialistRecommendation:
    """One evidence-backed specialist recommendation.

    Gate/advisory agents may still be present in a trace, but are never allowed
    to determine BUY or SELL direction.
    """

    agent_id: str
    intent: TradingIntent
    confidence: float
    evidence_score: float
    risk_score: float
    verified: bool
    rationale: str = ""
    evidence_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.agent_id.strip():
            raise ValueError("agent_id must not be empty")
        _percent(self.confidence, "confidence")
        _percent(self.evidence_score, "evidence_score")
        _percent(self.risk_score, "risk_score")


@dataclass(frozen=True, slots=True)
class DecisionQualitySignal:
    blocked: bool
    quality_score: float
    agreement: float
    reason: str = ""

    def __post_init__(self) -> None:
        _percent(self.quality_score, "quality_score")
        _percent(self.agreement, "agreement")


@dataclass(frozen=True, slots=True)
class GateSignal:
    gate: str
    verdict: GateVerdict
    reasons: tuple[str, ...] = ()
    max_notional_usdt: float | None = None

    def __post_init__(self) -> None:
        if not self.gate.strip():
            raise ValueError("gate must not be empty")
        if self.max_notional_usdt is not None:
            if not isfinite(float(self.max_notional_usdt)) or float(self.max_notional_usdt) < 0:
                raise ValueError("max_notional_usdt must be finite and non-negative")


@dataclass(frozen=True, slots=True)
class GeneralControllerDecision:
    preliminary_intent: TradingIntent
    final_intent: TradingIntent
    confidence: float
    blocked: bool
    reason: str
    buy_score: float
    sell_score: float
    contributing_agents: tuple[str, ...]
    ignored_agents: tuple[str, ...]
    gate_verdicts: tuple[tuple[str, str], ...]
    shadow: bool = True
    execution_authority: bool = False

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["preliminary_intent"] = self.preliminary_intent.value
        payload["final_intent"] = self.final_intent.value
        payload["gate_verdicts"] = dict(self.gate_verdicts)
        return payload


@dataclass(frozen=True, slots=True)
class _Preliminary:
    intent: TradingIntent
    confidence: float
    reason: str
    buy_score: float
    sell_score: float
    contributing_agents: tuple[str, ...]
    ignored_agents: tuple[str, ...]


class GeneralControllerV2:
    """Evidence synthesizer and final BUY/SELL/WAIT owner, shadow-only for now."""

    def __init__(
        self,
        *,
        min_quality_score: float = 55.0,
        min_agreement: float = 55.0,
        min_directional_agents: int = 2,
        min_direction_score: float = 0.30,
        min_direction_margin: float = 0.12,
    ) -> None:
        _percent(min_quality_score, "min_quality_score")
        _percent(min_agreement, "min_agreement")
        if min_directional_agents < 1:
            raise ValueError("min_directional_agents must be positive")
        if not 0.0 <= min_direction_score <= 1.0:
            raise ValueError("min_direction_score must be within 0..1")
        if not 0.0 <= min_direction_margin <= 1.0:
            raise ValueError("min_direction_margin must be within 0..1")
        self.min_quality_score = float(min_quality_score)
        self.min_agreement = float(min_agreement)
        self.min_directional_agents = int(min_directional_agents)
        self.min_direction_score = float(min_direction_score)
        self.min_direction_margin = float(min_direction_margin)

    def decide(
        self,
        recommendations: Iterable[SpecialistRecommendation],
        *,
        decision_quality: DecisionQualitySignal,
        gates: Iterable[GateSignal],
    ) -> GeneralControllerDecision:
        """Create a final shadow intent after mandatory veto/WAIT gates."""

        preliminary = self.preliminary(recommendations, decision_quality=decision_quality)
        gate_map = self._gate_map(gates)
        verdict_trace = tuple((name, gate_map[name].verdict.value) for name in sorted(gate_map))

        missing = tuple(name for name in _REQUIRED_GATES if name not in gate_map)
        if missing:
            return self._finish(
                preliminary,
                TradingIntent.WAIT,
                blocked=True,
                reason=f"missing mandatory gate(s): {', '.join(missing)}",
                gate_verdicts=verdict_trace,
            )

        blocked = [gate for gate in gate_map.values() if gate.verdict is GateVerdict.BLOCK]
        if blocked:
            details = self._gate_details(blocked)
            return self._finish(
                preliminary,
                TradingIntent.WAIT,
                blocked=True,
                reason=f"mandatory gate BLOCK: {details}",
                gate_verdicts=verdict_trace,
            )

        waiting = [gate for gate in gate_map.values() if gate.verdict is GateVerdict.WAIT]
        if waiting:
            details = self._gate_details(waiting)
            return self._finish(
                preliminary,
                TradingIntent.WAIT,
                blocked=False,
                reason=f"mandatory gate WAIT: {details}",
                gate_verdicts=verdict_trace,
            )

        portfolio = gate_map["portfolio_engine"]
        if portfolio.max_notional_usdt is not None and portfolio.max_notional_usdt <= 0:
            return self._finish(
                preliminary,
                TradingIntent.WAIT,
                blocked=False,
                reason="portfolio_engine permits no position notional",
                gate_verdicts=verdict_trace,
            )

        if preliminary.intent is TradingIntent.WAIT:
            return self._finish(
                preliminary,
                TradingIntent.WAIT,
                blocked=False,
                reason=preliminary.reason,
                gate_verdicts=verdict_trace,
            )

        return self._finish(
            preliminary,
            preliminary.intent,
            blocked=False,
            reason=f"General Controller finalized {preliminary.intent.value}; all mandatory gates PASS",
            gate_verdicts=verdict_trace,
        )

    def preliminary(
        self,
        recommendations: Iterable[SpecialistRecommendation],
        *,
        decision_quality: DecisionQualitySignal,
    ) -> _Preliminary:
        """Synthesize specialist evidence without allowing gates to create direction."""

        rows = tuple(recommendations)
        ignored: list[str] = []
        directional: list[tuple[SpecialistRecommendation, float]] = []

        for item in rows:
            agent = item.agent_id.strip()
            if agent in _NON_DIRECTIONAL_AGENTS or item.intent is TradingIntent.WAIT or not item.verified:
                ignored.append(agent)
                continue
            weight = self._weight(item)
            if weight <= 0:
                ignored.append(agent)
                continue
            directional.append((item, weight))

        contributing = tuple(sorted({item.agent_id.strip() for item, _ in directional}))
        ignored_agents = tuple(sorted(set(ignored)))
        buy_score = sum(weight for item, weight in directional if item.intent is TradingIntent.BUY)
        sell_score = sum(weight for item, weight in directional if item.intent is TradingIntent.SELL)

        if decision_quality.blocked:
            return _Preliminary(
                TradingIntent.WAIT,
                0.0,
                f"Decision Quality blocked evidence: {decision_quality.reason or 'unspecified'}",
                buy_score,
                sell_score,
                contributing,
                ignored_agents,
            )
        if decision_quality.quality_score < self.min_quality_score:
            return _Preliminary(
                TradingIntent.WAIT,
                decision_quality.quality_score,
                "Decision Quality score below General Controller threshold",
                buy_score,
                sell_score,
                contributing,
                ignored_agents,
            )
        if decision_quality.agreement < self.min_agreement:
            return _Preliminary(
                TradingIntent.WAIT,
                decision_quality.agreement,
                "Decision Quality agreement below General Controller threshold",
                buy_score,
                sell_score,
                contributing,
                ignored_agents,
            )
        if len(directional) < self.min_directional_agents:
            return _Preliminary(
                TradingIntent.WAIT,
                0.0,
                "insufficient verified directional specialists",
                buy_score,
                sell_score,
                contributing,
                ignored_agents,
            )

        total = buy_score + sell_score
        if total <= 0:
            return _Preliminary(
                TradingIntent.WAIT,
                0.0,
                "verified evidence has no directional strength",
                buy_score,
                sell_score,
                contributing,
                ignored_agents,
            )
        winner = max(buy_score, sell_score)
        loser = min(buy_score, sell_score)
        normalized_winner = winner / len(directional)
        normalized_margin = (winner - loser) / total
        confidence = min(100.0, max(0.0, 100.0 * winner / total))
        if normalized_winner < self.min_direction_score or normalized_margin < self.min_direction_margin:
            return _Preliminary(
                TradingIntent.WAIT,
                confidence,
                "directional evidence is too weak or contradictory",
                buy_score,
                sell_score,
                contributing,
                ignored_agents,
            )

        intent = TradingIntent.BUY if buy_score > sell_score else TradingIntent.SELL
        return _Preliminary(
            intent,
            confidence,
            f"General Controller preliminary {intent.value} from verified specialist evidence",
            buy_score,
            sell_score,
            contributing,
            ignored_agents,
        )

    @staticmethod
    def _weight(item: SpecialistRecommendation) -> float:
        confidence = item.confidence / 100.0
        evidence = item.evidence_score / 100.0
        residual_risk = 1.0 - item.risk_score / 100.0
        return confidence * evidence * max(residual_risk, 0.0)

    @staticmethod
    def _gate_map(gates: Iterable[GateSignal]) -> dict[str, GateSignal]:
        result: dict[str, GateSignal] = {}
        for gate in gates:
            name = gate.gate.strip()
            if name in result:
                raise ValueError(f"duplicate gate: {name}")
            result[name] = gate
        return result

    @staticmethod
    def _gate_details(gates: Iterable[GateSignal]) -> str:
        parts: list[str] = []
        for gate in gates:
            reason = "; ".join(item.strip() for item in gate.reasons if item.strip()) or gate.verdict.value
            parts.append(f"{gate.gate}={reason}")
        return ", ".join(parts)

    @staticmethod
    def _finish(
        preliminary: _Preliminary,
        final_intent: TradingIntent,
        *,
        blocked: bool,
        reason: str,
        gate_verdicts: tuple[tuple[str, str], ...],
    ) -> GeneralControllerDecision:
        return GeneralControllerDecision(
            preliminary_intent=preliminary.intent,
            final_intent=final_intent,
            confidence=preliminary.confidence,
            blocked=blocked,
            reason=reason,
            buy_score=preliminary.buy_score,
            sell_score=preliminary.sell_score,
            contributing_agents=preliminary.contributing_agents,
            ignored_agents=preliminary.ignored_agents,
            gate_verdicts=gate_verdicts,
            shadow=True,
            execution_authority=False,
        )


def _percent(value: float, field: str) -> None:
    if isinstance(value, bool) or not isfinite(float(value)) or not 0.0 <= float(value) <= 100.0:
        raise ValueError(f"{field} must be finite and within 0..100")


__all__ = [
    "DecisionQualitySignal",
    "GateSignal",
    "GateVerdict",
    "GeneralControllerDecision",
    "GeneralControllerV2",
    "SpecialistRecommendation",
    "TradingIntent",
]
