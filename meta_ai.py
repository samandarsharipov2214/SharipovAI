"""Adaptive Meta AI for SharipovAI.

Implements five additive stages without granting agents execution authority:
reputation, regime-aware scoring, post-decision audit, dynamic consensus,
and optimizer recommendations. The module is deterministic and dependency-free.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import UTC, datetime
from math import sqrt
from statistics import mean
from typing import Iterable, Mapping, Sequence

# Order is also the deterministic capital-protection tie-break priority.
ACTION_ORDER = ("BLOCK", "WAIT", "HOLD", "SELL", "BUY")
VALID_ACTIONS = frozenset(ACTION_ORDER)
VALID_REGIMES = frozenset({"bull", "bear", "sideways", "high_volatility", "unknown"})
_VETO_AGENT_IDS = {
    "risk",
    "risk_engine",
    "security",
    "security_guard",
    "policy_guard",
    "security_cyber",
    "security_cyber_ai",
}


def _finite(value: object, name: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a finite number")
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a finite number") from exc
    if not math.isfinite(parsed):
        raise ValueError(f"{name} must be a finite number")
    return parsed


def _ratio(value: object, name: str) -> float:
    parsed = _finite(value, name)
    if not 0.0 <= parsed <= 1.0:
        raise ValueError(f"{name} must be within 0..1")
    return parsed


def _clip(value: object, low: float = 0.0, high: float = 1.0) -> float:
    parsed = _finite(value, "value")
    return max(low, min(high, parsed))


def _agent_key(agent_id: str) -> str:
    return str(agent_id).strip().lower().replace(" ", "_").replace("-", "_")


def _has_veto_authority(agent_id: str) -> bool:
    """Only canonical Risk and Security owners may issue an unconditional block."""

    key = _agent_key(agent_id)
    return key in _VETO_AGENT_IDS or key.startswith("risk_engine_") or key.startswith("security_guard_")


@dataclass(frozen=True, slots=True)
class AgentOpinion:
    agent_id: str
    action: str
    confidence: float
    evidence_score: float = 0.5
    risk_score: float = 0.5
    regime: str = "unknown"
    rationale: str = ""

    def __post_init__(self) -> None:
        agent_id = str(self.agent_id).strip()
        action = str(self.action).upper().strip()
        regime = str(self.regime).strip()
        if not agent_id:
            raise ValueError("agent_id must not be empty")
        if action not in VALID_ACTIONS:
            raise ValueError(f"Unsupported action: {self.action}")
        if regime not in VALID_REGIMES:
            raise ValueError(f"Unsupported regime: {self.regime}")
        object.__setattr__(self, "agent_id", agent_id)
        object.__setattr__(self, "action", action)
        object.__setattr__(self, "confidence", _ratio(self.confidence, "confidence"))
        object.__setattr__(self, "evidence_score", _ratio(self.evidence_score, "evidence_score"))
        object.__setattr__(self, "risk_score", _ratio(self.risk_score, "risk_score"))
        object.__setattr__(self, "regime", regime)
        object.__setattr__(self, "rationale", str(self.rationale))


@dataclass(frozen=True, slots=True)
class PredictionOutcome:
    agent_id: str
    predicted_action: str
    realized_action: str
    confidence: float
    pnl_contribution: float
    drawdown_contribution: float
    regime: str = "unknown"
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        agent_id = str(self.agent_id).strip()
        predicted = str(self.predicted_action).upper().strip()
        realized = str(self.realized_action).upper().strip()
        regime = str(self.regime).strip()
        if not agent_id:
            raise ValueError("agent_id must not be empty")
        if predicted not in VALID_ACTIONS:
            raise ValueError(f"Unsupported predicted action: {self.predicted_action}")
        if realized not in VALID_ACTIONS:
            raise ValueError(f"Unsupported realized action: {self.realized_action}")
        if regime not in VALID_REGIMES:
            raise ValueError(f"Unsupported regime: {self.regime}")
        if not isinstance(self.timestamp, datetime) or self.timestamp.tzinfo is None:
            raise ValueError("timestamp must be timezone-aware")
        drawdown = _finite(self.drawdown_contribution, "drawdown_contribution")
        if drawdown < 0:
            raise ValueError("drawdown_contribution must be non-negative")
        object.__setattr__(self, "agent_id", agent_id)
        object.__setattr__(self, "predicted_action", predicted)
        object.__setattr__(self, "realized_action", realized)
        object.__setattr__(self, "confidence", _ratio(self.confidence, "confidence"))
        object.__setattr__(self, "pnl_contribution", _finite(self.pnl_contribution, "pnl_contribution"))
        object.__setattr__(self, "drawdown_contribution", drawdown)
        object.__setattr__(self, "regime", regime)
        object.__setattr__(self, "timestamp", self.timestamp.astimezone(UTC))

    @property
    def correct(self) -> bool:
        return self.predicted_action == self.realized_action


@dataclass(slots=True)
class AgentReputation:
    agent_id: str
    total_predictions: int = 0
    correct_predictions: int = 0
    confidence_error_sum: float = 0.0
    pnl_contribution: float = 0.0
    drawdown_contribution: float = 0.0
    regime_total: dict[str, int] = field(default_factory=dict)
    regime_correct: dict[str, int] = field(default_factory=dict)

    def record(self, outcome: PredictionOutcome) -> None:
        if outcome.agent_id != self.agent_id:
            raise ValueError("outcome agent_id does not match reputation owner")
        self.total_predictions += 1
        self.correct_predictions += int(outcome.correct)
        target = 1.0 if outcome.correct else 0.0
        self.confidence_error_sum += abs(outcome.confidence - target)
        self.pnl_contribution += outcome.pnl_contribution
        self.drawdown_contribution += outcome.drawdown_contribution
        self.regime_total[outcome.regime] = self.regime_total.get(outcome.regime, 0) + 1
        self.regime_correct[outcome.regime] = self.regime_correct.get(outcome.regime, 0) + int(outcome.correct)

    @property
    def accuracy(self) -> float:
        return self.correct_predictions / self.total_predictions if self.total_predictions else 0.5

    @property
    def confidence_calibration(self) -> float:
        if not self.total_predictions:
            return 0.5
        return 1.0 - self.confidence_error_sum / self.total_predictions

    def regime_accuracy(self, regime: str) -> float:
        if regime not in VALID_REGIMES:
            raise ValueError(f"Unsupported regime: {regime}")
        total = self.regime_total.get(regime, 0)
        return self.regime_correct.get(regime, 0) / total if total else self.accuracy

    def weight(self, regime: str, min_weight: float = 0.15, max_weight: float = 1.5) -> float:
        minimum = _finite(min_weight, "min_weight")
        maximum = _finite(max_weight, "max_weight")
        if minimum <= 0 or maximum < minimum:
            raise ValueError("invalid reputation weight bounds")
        sample_factor = min(1.0, self.total_predictions / 30.0)
        accuracy = 0.6 * self.accuracy + 0.4 * self.regime_accuracy(regime)
        calibration = self.confidence_calibration
        pnl_quality = 0.5 + 0.5 * (self.pnl_contribution / (abs(self.pnl_contribution) + 100.0))
        drawdown_penalty = 1.0 / (1.0 + self.drawdown_contribution / 100.0)
        raw = (0.55 * accuracy + 0.25 * calibration + 0.20 * pnl_quality) * drawdown_penalty
        cold_start_blend = 0.5 * (1.0 - sample_factor) + raw * sample_factor
        return max(minimum, min(maximum, cold_start_blend * maximum))


@dataclass(frozen=True, slots=True)
class ConsensusResult:
    action: str
    confidence: float
    agreement: float
    weighted_scores: Mapping[str, float]
    dissenting_agents: tuple[str, ...]
    blocked: bool
    reason: str


@dataclass(frozen=True, slots=True)
class DecisionAudit:
    selected_action: str
    realized_action: str
    winning_agents: tuple[str, ...]
    losing_agents: tuple[str, ...]
    abstaining_agents: tuple[str, ...]
    confidence_gap: float
    lessons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class OptimizerRecommendation:
    kind: str
    agents: tuple[str, ...]
    severity: str
    reason: str
    automatic_action_allowed: bool = False


class MetaAI:
    """Coordinator-side evaluator. It never executes trades or removes agents."""

    def __init__(self) -> None:
        self._reputations: dict[str, AgentReputation] = {}
        self._history: list[PredictionOutcome] = []

    def reputation(self, agent_id: str) -> AgentReputation:
        clean = str(agent_id).strip()
        if not clean:
            raise ValueError("agent_id must not be empty")
        return self._reputations.setdefault(clean, AgentReputation(agent_id=clean))

    def record_outcomes(self, outcomes: Iterable[PredictionOutcome]) -> None:
        for outcome in outcomes:
            if not isinstance(outcome, PredictionOutcome):
                raise TypeError("outcome must be PredictionOutcome")
            self.reputation(outcome.agent_id).record(outcome)
            self._history.append(outcome)

    def reputations_snapshot(self, regime: str = "unknown") -> dict[str, dict[str, float | int]]:
        if regime not in VALID_REGIMES:
            raise ValueError(f"Unsupported regime: {regime}")
        return {
            agent_id: {
                "total_predictions": rep.total_predictions,
                "accuracy": round(rep.accuracy, 6),
                "regime_accuracy": round(rep.regime_accuracy(regime), 6),
                "confidence_calibration": round(rep.confidence_calibration, 6),
                "pnl_contribution": round(rep.pnl_contribution, 6),
                "drawdown_contribution": round(rep.drawdown_contribution, 6),
                "current_weight": round(rep.weight(regime), 6),
            }
            for agent_id, rep in sorted(self._reputations.items())
        }

    def dynamic_consensus(
        self,
        opinions: Sequence[AgentOpinion],
        *,
        regime: str = "unknown",
        min_evidence: float = 0.35,
        max_risk: float = 0.80,
        min_agreement: float = 0.55,
    ) -> ConsensusResult:
        if regime not in VALID_REGIMES:
            raise ValueError(f"Unsupported regime: {regime}")
        min_evidence = _ratio(min_evidence, "min_evidence")
        max_risk = _ratio(max_risk, "max_risk")
        min_agreement = _ratio(min_agreement, "min_agreement")
        if not opinions:
            return ConsensusResult("WAIT", 0.0, 0.0, {action: 0.0 for action in ACTION_ORDER}, (), True, "No agent opinions")

        scores = {action: 0.0 for action in ACTION_ORDER}
        agent_votes: list[tuple[str, str, float]] = []
        total_weight = 0.0
        hard_blockers: list[str] = []
        suppressed: list[str] = []
        for opinion in opinions:
            if not isinstance(opinion, AgentOpinion):
                raise TypeError("opinions must contain AgentOpinion values")
            veto_authority = _has_veto_authority(opinion.agent_id)
            unsafe_evidence = opinion.evidence_score < min_evidence
            unsafe_risk = opinion.risk_score > max_risk
            requested_block = opinion.action == "BLOCK"

            if veto_authority and (requested_block or unsafe_evidence or unsafe_risk):
                hard_blockers.append(opinion.agent_id)
                agent_votes.append((opinion.agent_id, "BLOCK", 0.0))
                continue
            if requested_block or unsafe_evidence or unsafe_risk:
                suppressed.append(opinion.agent_id)
                agent_votes.append((opinion.agent_id, "WAIT", 0.0))
                continue

            rep_weight = self.reputation(opinion.agent_id).weight(regime)
            quality = opinion.confidence * opinion.evidence_score * (1.0 - opinion.risk_score * 0.5)
            vote_weight = rep_weight * quality
            if not math.isfinite(vote_weight) or vote_weight < 0:
                raise ValueError("calculated vote weight is invalid")
            scores[opinion.action] += vote_weight
            total_weight += vote_weight
            agent_votes.append((opinion.agent_id, opinion.action, vote_weight))

        if hard_blockers:
            dissent = tuple(sorted(set(hard_blockers + suppressed)))
            return ConsensusResult("BLOCK", 1.0, 0.0, scores, dissent, True, "Canonical Risk/Security veto activated")
        if total_weight <= 0:
            return ConsensusResult(
                "WAIT",
                0.0,
                0.0,
                scores,
                tuple(sorted(set(suppressed))),
                True,
                "No eligible agent opinions after evidence and risk filtering",
            )

        priority = {action: index for index, action in enumerate(ACTION_ORDER)}
        ranked = sorted(ACTION_ORDER, key=lambda action: (-scores[action], priority[action]))
        action, second_action = ranked[0], ranked[1]
        top_score, second_score = scores[action], scores[second_action]
        agreement = _ratio(top_score / total_weight, "agreement")
        confidence = _clip(0.7 * agreement + 0.3 * (top_score - second_score) / max(total_weight, 1e-9))
        dissent = tuple(sorted(set([agent for agent, vote, _ in agent_votes if vote != action] + suppressed)))
        if agreement < min_agreement:
            return ConsensusResult("WAIT", confidence, agreement, scores, dissent, True, "Insufficient agreement")
        reason = "Regime-aware weighted consensus"
        if suppressed:
            reason += f"; excluded {len(set(suppressed))} non-authoritative unsafe opinion(s)"
        return ConsensusResult(action, confidence, agreement, scores, dissent, False, reason)

    def audit_decision(
        self,
        opinions: Sequence[AgentOpinion],
        *,
        selected_action: str,
        realized_action: str,
    ) -> DecisionAudit:
        selected = str(selected_action).upper().strip()
        realized = str(realized_action).upper().strip()
        if selected not in VALID_ACTIONS or realized not in VALID_ACTIONS:
            raise ValueError("selected_action and realized_action must be canonical actions")
        winners = tuple(sorted(o.agent_id for o in opinions if o.action == realized))
        losers = tuple(sorted(o.agent_id for o in opinions if o.action not in {realized, "WAIT", "HOLD"}))
        abstainers = tuple(sorted(o.agent_id for o in opinions if o.action in {"WAIT", "HOLD"}))
        selected_conf = [o.confidence for o in opinions if o.action == selected]
        opposing_conf = [o.confidence for o in opinions if o.action != selected]
        gap = (mean(selected_conf) if selected_conf else 0.0) - (mean(opposing_conf) if opposing_conf else 0.0)
        lessons: list[str] = []
        if selected != realized:
            lessons.append("Final decision differed from realized best action; review evidence and regime classification.")
        if losers:
            lessons.append("Reduce influence only through measured reputation, never by automatic agent deletion.")
        if not winners:
            lessons.append("No agent predicted the realized action; expand independent analysis coverage.")
        return DecisionAudit(selected, realized, winners, losers, abstainers, gap, tuple(lessons))

    def optimizer_recommendations(
        self,
        *,
        regime: str = "unknown",
        similarity: Mapping[tuple[str, str], float] | None = None,
    ) -> tuple[OptimizerRecommendation, ...]:
        if regime not in VALID_REGIMES:
            raise ValueError(f"Unsupported regime: {regime}")
        recommendations: list[OptimizerRecommendation] = []
        for agent_id, rep in sorted(self._reputations.items()):
            if rep.total_predictions >= 20 and rep.accuracy < 0.45:
                recommendations.append(OptimizerRecommendation(
                    "RETRAIN_OR_REVIEW", (agent_id,), "high",
                    f"Accuracy {rep.accuracy:.2%} after {rep.total_predictions} predictions.",
                ))
            if rep.total_predictions >= 20 and rep.confidence_calibration < 0.55:
                recommendations.append(OptimizerRecommendation(
                    "RECALIBRATE_CONFIDENCE", (agent_id,), "medium",
                    f"Confidence calibration {rep.confidence_calibration:.2%}.",
                ))
            if rep.drawdown_contribution > max(100.0, abs(rep.pnl_contribution) * 1.5):
                recommendations.append(OptimizerRecommendation(
                    "LIMIT_WEIGHT", (agent_id,), "high",
                    "Drawdown contribution is disproportionate to PnL contribution.",
                ))
        for (left, right), raw_value in sorted((similarity or {}).items()):
            value = _ratio(raw_value, "similarity")
            if left != right and value >= 0.92:
                recommendations.append(OptimizerRecommendation(
                    "DUPLICATION_REVIEW", tuple(sorted((left, right))), "low",
                    f"Opinion similarity {value:.2%}; verify that methods and data sources are genuinely independent.",
                ))
        return tuple(recommendations)

    def decision_quality_score(self, result: ConsensusResult) -> float:
        risk_gate = 0.0 if result.blocked and result.action == "BLOCK" else 1.0
        diversification = 1.0 / sqrt(max(1, len(result.dissenting_agents) + 1))
        return _clip(0.55 * result.confidence + 0.30 * result.agreement + 0.15 * risk_gate * diversification)
