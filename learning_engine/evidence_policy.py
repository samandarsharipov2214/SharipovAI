"""Fail-closed policy for evidence-driven self-learning.

This module validates learning evidence only.  It has no execution, deployment,
credential, campaign, or capital authority.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Any, Mapping, Sequence

_ALLOWED_SOURCES = {"paper", "testnet"}
_FORBIDDEN_CLASSES = {"synthetic", "fixture", "mock", "demo", "simulation"}
_ALLOWED_ACTIONS = {"BUY", "SELL", "HOLD", "WAIT", "BLOCK"}


@dataclass(frozen=True, slots=True)
class SelfLearningPolicy:
    minimum_outcomes: int = 30
    minimum_agent_outcomes: int = 12
    minimum_regimes: int = 2
    minimum_direction_accuracy: float = 0.52
    maximum_calibration_error: float = 0.30
    minimum_attributed_pnl: float = 0.0
    maximum_drawdown_contribution: float = 10.0
    minimum_challenger_improvement: float = 0.02
    maximum_weight_shift: float = 0.15

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class AgentEvidence:
    agent_id: str
    action: str
    confidence: float
    evidence_score: float

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "AgentEvidence":
        agent_id = _identifier(value.get("agent_id") or value.get("name"), "agent_id")
        action = str(value.get("action") or value.get("decision") or "WAIT").strip().upper()
        if action not in _ALLOWED_ACTIONS:
            raise ValueError(f"unsupported action for {agent_id}: {action}")
        confidence = _bounded_number(value.get("confidence"), "confidence", 0.0, 100.0)
        evidence_score = _bounded_number(
            value.get("evidence_score", value.get("evidence", 1.0)),
            "evidence_score",
            0.0,
            1.0,
        )
        if value.get("learning_eligible") is False or value.get("evidence_eligible") is False:
            raise ValueError(f"agent evidence is not learning eligible: {agent_id}")
        evidence_class = str(value.get("evidence_class") or "verified_market").strip().lower()
        if evidence_class in _FORBIDDEN_CLASSES:
            raise ValueError(f"synthetic evidence is forbidden: {agent_id}")
        if value.get("verified_market_data") is False or value.get("data_verified") is False:
            raise ValueError(f"unverified market evidence is forbidden: {agent_id}")
        return cls(
            agent_id=agent_id,
            action=action,
            confidence=confidence,
            evidence_score=evidence_score,
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class OutcomeEvidence:
    outcome_id: str
    decision_id: str
    source: str
    selected_action: str
    realized_action: str
    net_pnl: float
    drawdown_contribution: float
    regime: str
    agents: tuple[AgentEvidence, ...]
    occurred_at_ms: int
    evidence_class: str = "verified_market"
    verified_market_data: bool = True

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "OutcomeEvidence":
        source = str(value.get("source") or value.get("environment") or "").strip().lower()
        if source not in _ALLOWED_SOURCES:
            raise ValueError("learning source must be paper or testnet")
        evidence_class = str(value.get("evidence_class") or "verified_market").strip().lower()
        if evidence_class in _FORBIDDEN_CLASSES:
            raise ValueError("synthetic outcome evidence is forbidden")
        if value.get("verified_market_data") is not True:
            raise ValueError("verified market evidence is required")
        selected = str(value.get("selected_action") or "WAIT").strip().upper()
        realized = str(value.get("realized_action") or "HOLD").strip().upper()
        if selected not in _ALLOWED_ACTIONS or realized not in _ALLOWED_ACTIONS:
            raise ValueError("invalid selected or realized action")
        raw_agents = value.get("agents") or value.get("opinions") or []
        if not isinstance(raw_agents, Sequence) or isinstance(raw_agents, (str, bytes)):
            raise TypeError("agents must be a sequence")
        agents = tuple(AgentEvidence.from_mapping(item) for item in raw_agents if isinstance(item, Mapping))
        if not agents:
            raise ValueError("at least one verified agent opinion is required")
        identifiers = [item.agent_id for item in agents]
        if len(set(identifiers)) != len(identifiers):
            raise ValueError("duplicate agent evidence is forbidden")
        occurred = int(value.get("occurred_at_ms") or value.get("settled_at_ms") or 0)
        if occurred <= 0:
            raise ValueError("occurred_at_ms must be positive")
        return cls(
            outcome_id=_identifier(value.get("outcome_id"), "outcome_id"),
            decision_id=_identifier(value.get("decision_id"), "decision_id"),
            source=source,
            selected_action=selected,
            realized_action=realized,
            net_pnl=_finite(value.get("net_pnl"), "net_pnl"),
            drawdown_contribution=max(0.0, _finite(value.get("drawdown_contribution"), "drawdown_contribution")),
            regime=_identifier(value.get("regime") or "unknown", "regime"),
            agents=agents,
            occurred_at_ms=occurred,
            evidence_class=evidence_class,
            verified_market_data=True,
        )

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["agents"] = [item.to_dict() for item in self.agents]
        return payload


def _identifier(value: Any, name: str) -> str:
    clean = str(value or "").strip()
    if not clean or len(clean) > 200:
        raise ValueError(f"invalid {name}")
    if any(character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.:-" for character in clean):
        raise ValueError(f"invalid {name}")
    return clean


def _finite(value: Any, name: str) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be numeric") from exc
    if not math.isfinite(parsed):
        raise ValueError(f"{name} must be finite")
    return parsed


def _bounded_number(value: Any, name: str, minimum: float, maximum: float) -> float:
    parsed = _finite(value, name)
    if not minimum <= parsed <= maximum:
        raise ValueError(f"{name} must be within [{minimum}, {maximum}]")
    return parsed


__all__ = ["AgentEvidence", "OutcomeEvidence", "SelfLearningPolicy"]
