"""Immutable outcome attribution and persistent agent learning metrics."""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any, Mapping

from storage import ProjectDatabase, VersionConflict, list_json_items

from .evidence_policy import OutcomeEvidence

_OUTCOME_NAMESPACE = "self_learning_outcomes"
_AGENT_NAMESPACE = "self_learning_agent_metrics"
_EVENT_NAMESPACE = "self_learning_events"


@dataclass(frozen=True, slots=True)
class AgentAttribution:
    agent_id: str
    action: str
    direction_correct: bool
    confidence: float
    confidence_error: float
    evidence_score: float
    pnl_attribution: float
    drawdown_attribution: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class OutcomeAttributionService:
    """Persist one verified outcome and repair derived agent metrics idempotently."""

    def __init__(self, database: ProjectDatabase | None = None) -> None:
        self.database = database or ProjectDatabase()
        self.database.initialize()

    def record(self, evidence: OutcomeEvidence | Mapping[str, Any]) -> dict[str, Any]:
        outcome = evidence if isinstance(evidence, OutcomeEvidence) else OutcomeEvidence.from_mapping(evidence)
        evidence_sha = _digest(outcome.to_dict())
        existing = self.database.get_json(_OUTCOME_NAMESPACE, outcome.outcome_id)
        if existing is not None:
            document = dict(existing["value"])
            if str(document.get("evidence_sha256") or "") != evidence_sha:
                raise ValueError("conflicting outcome evidence is immutable")
            self._repair_agent_projection(outcome, document)
            return {**document, "version": int(existing["version"]), "idempotent": True}

        attributions = self._attribute(outcome)
        document = {
            "outcome_id": outcome.outcome_id,
            "decision_id": outcome.decision_id,
            "source": outcome.source,
            "selected_action": outcome.selected_action,
            "realized_action": outcome.realized_action,
            "net_pnl": outcome.net_pnl,
            "drawdown_contribution": outcome.drawdown_contribution,
            "regime": outcome.regime,
            "occurred_at_ms": outcome.occurred_at_ms,
            "evidence_class": outcome.evidence_class,
            "verified_market_data": True,
            "attributions": [item.to_dict() for item in attributions],
            "evidence_sha256": evidence_sha,
            "execution_authority": False,
            "runtime_flags_changed": False,
        }
        self._verify_reconciliation(document)
        version = self.database.put_json(
            _OUTCOME_NAMESPACE,
            outcome.outcome_id,
            document,
            expected_version=0,
        )
        self._repair_agent_projection(outcome, document)
        event_id = self.database.append_event(
            _EVENT_NAMESPACE,
            "outcome_attribution",
            outcome.outcome_id,
            {
                "decision_id": outcome.decision_id,
                "source": outcome.source,
                "agent_count": len(attributions),
                "evidence_sha256": evidence_sha,
            },
            event_id=f"self-learning-outcome-{outcome.outcome_id}",
            created_at_ms=outcome.occurred_at_ms,
        )
        return {**document, "version": version, "event_id": event_id, "idempotent": False}

    def get(self, outcome_id: str) -> dict[str, Any] | None:
        current = self.database.get_json(_OUTCOME_NAMESPACE, str(outcome_id).strip())
        if current is None:
            return None
        return {**dict(current["value"]), "version": int(current["version"])}

    def list_outcomes(self, *, limit: int = 500) -> list[dict[str, Any]]:
        return [
            {**dict(row["value"]), "version": int(row["version"])}
            for row in list_json_items(
                self.database,
                _OUTCOME_NAMESPACE,
                limit=min(max(int(limit), 1), 5_000),
                newest_first=True,
            )
        ]

    def agent_metrics(self, agent_id: str | None = None, *, limit: int = 500) -> list[dict[str, Any]]:
        rows = [
            {**dict(row["value"]), "version": int(row["version"])}
            for row in list_json_items(
                self.database,
                _AGENT_NAMESPACE,
                limit=min(max(int(limit), 1), 5_000),
                newest_first=True,
            )
        ]
        if agent_id is None:
            return rows
        clean = str(agent_id).strip()
        return [item for item in rows if str(item.get("agent_id") or "") == clean]

    def summary(self) -> dict[str, Any]:
        outcomes = self.list_outcomes(limit=10_000)
        for document in outcomes:
            outcome = _outcome_from_document(document)
            self._repair_agent_projection(outcome, document)
        agents = self.agent_metrics(limit=10_000)
        regimes = sorted({str(item.get("regime") or "unknown") for item in outcomes})
        return {
            "status": "ok",
            "verified_outcome_count": len(outcomes),
            "agent_count": len(agents),
            "regime_count": len(regimes),
            "regimes": regimes,
            "net_pnl": round(sum(float(item.get("net_pnl") or 0.0) for item in outcomes), 12),
            "drawdown_contribution": round(
                sum(float(item.get("drawdown_contribution") or 0.0) for item in outcomes), 12
            ),
            "execution_authority": False,
            "runtime_flags_changed": False,
        }

    def _attribute(self, outcome: OutcomeEvidence) -> tuple[AgentAttribution, ...]:
        contributors = [item for item in outcome.agents if item.action == outcome.selected_action]
        if not contributors:
            contributors = list(outcome.agents)
        raw_weights = [
            max(item.confidence / 100.0, 0.01) * max(item.evidence_score, 0.01)
            for item in contributors
        ]
        total = sum(raw_weights)
        weights = [value / total for value in raw_weights]
        contribution_by_agent = {
            item.agent_id: weight
            for item, weight in zip(contributors, weights, strict=True)
        }
        result: list[AgentAttribution] = []
        for agent in outcome.agents:
            weight = contribution_by_agent.get(agent.agent_id, 0.0)
            correct = agent.action == outcome.realized_action
            result.append(
                AgentAttribution(
                    agent_id=agent.agent_id,
                    action=agent.action,
                    direction_correct=correct,
                    confidence=agent.confidence,
                    confidence_error=abs(agent.confidence / 100.0 - (1.0 if correct else 0.0)),
                    evidence_score=agent.evidence_score,
                    pnl_attribution=outcome.net_pnl * weight,
                    drawdown_attribution=outcome.drawdown_contribution * weight,
                )
            )
        return tuple(result)

    def _repair_agent_projection(self, outcome: OutcomeEvidence, document: Mapping[str, Any]) -> None:
        rows = document.get("attributions")
        if not isinstance(rows, list):
            raise RuntimeError("stored outcome attributions are invalid")
        self._verify_reconciliation(document)
        for row in rows:
            if not isinstance(row, Mapping):
                raise RuntimeError("stored agent attribution is invalid")
            self._update_agent(outcome, AgentAttribution(**dict(row)))

    def _update_agent(self, outcome: OutcomeEvidence, attribution: AgentAttribution) -> None:
        for _ in range(5):
            current = self.database.get_json(_AGENT_NAMESPACE, attribution.agent_id)
            version = int(current["version"]) if current else 0
            payload = dict(current["value"]) if current else {
                "agent_id": attribution.agent_id,
                "outcome_count": 0,
                "correct_count": 0,
                "confidence_error_sum": 0.0,
                "attributed_pnl": 0.0,
                "attributed_drawdown": 0.0,
                "regimes": {},
                "sources": {},
                "applied_outcomes": [],
            }
            applied = [str(item) for item in payload.get("applied_outcomes") or []]
            if outcome.outcome_id in applied:
                return
            payload["outcome_count"] = int(payload.get("outcome_count", 0)) + 1
            payload["correct_count"] = int(payload.get("correct_count", 0)) + int(attribution.direction_correct)
            payload["confidence_error_sum"] = float(payload.get("confidence_error_sum", 0.0)) + attribution.confidence_error
            payload["attributed_pnl"] = float(payload.get("attributed_pnl", 0.0)) + attribution.pnl_attribution
            payload["attributed_drawdown"] = float(payload.get("attributed_drawdown", 0.0)) + attribution.drawdown_attribution
            regimes = dict(payload.get("regimes") or {})
            regimes[outcome.regime] = int(regimes.get(outcome.regime, 0)) + 1
            payload["regimes"] = regimes
            sources = dict(payload.get("sources") or {})
            sources[outcome.source] = int(sources.get(outcome.source, 0)) + 1
            payload["sources"] = sources
            payload["applied_outcomes"] = [*applied, outcome.outcome_id]
            count = int(payload["outcome_count"])
            payload["direction_accuracy"] = float(payload["correct_count"]) / count
            payload["mean_confidence_error"] = float(payload["confidence_error_sum"]) / count
            payload["learning_score"] = _learning_score(payload)
            payload["updated_at_ms"] = outcome.occurred_at_ms
            try:
                self.database.put_json(
                    _AGENT_NAMESPACE,
                    attribution.agent_id,
                    payload,
                    expected_version=version,
                )
                return
            except VersionConflict:
                continue
        raise RuntimeError("concurrent self-learning attribution conflict")

    @staticmethod
    def _verify_reconciliation(document: Mapping[str, Any]) -> None:
        rows = document.get("attributions") or []
        pnl = sum(float(item.get("pnl_attribution") or 0.0) for item in rows)
        drawdown = sum(float(item.get("drawdown_attribution") or 0.0) for item in rows)
        if abs(pnl - float(document.get("net_pnl") or 0.0)) > 1e-9:
            raise RuntimeError("PnL attribution does not reconcile")
        if abs(drawdown - float(document.get("drawdown_contribution") or 0.0)) > 1e-9:
            raise RuntimeError("drawdown attribution does not reconcile")


def _outcome_from_document(document: Mapping[str, Any]) -> OutcomeEvidence:
    agents = []
    for row in document.get("attributions") or []:
        if isinstance(row, Mapping):
            agents.append({
                "agent_id": row.get("agent_id"),
                "action": row.get("action"),
                "confidence": row.get("confidence"),
                "evidence_score": row.get("evidence_score"),
                "evidence_class": "verified_market",
                "verified_market_data": True,
            })
    return OutcomeEvidence.from_mapping({
        "outcome_id": document.get("outcome_id"),
        "decision_id": document.get("decision_id"),
        "source": document.get("source"),
        "selected_action": document.get("selected_action"),
        "realized_action": document.get("realized_action"),
        "net_pnl": document.get("net_pnl"),
        "drawdown_contribution": document.get("drawdown_contribution"),
        "regime": document.get("regime"),
        "agents": agents,
        "occurred_at_ms": document.get("occurred_at_ms"),
        "evidence_class": document.get("evidence_class"),
        "verified_market_data": document.get("verified_market_data") is True,
    })


def _learning_score(payload: Mapping[str, Any]) -> float:
    accuracy = float(payload.get("direction_accuracy") or 0.0)
    calibration = 1.0 - min(max(float(payload.get("mean_confidence_error") or 1.0), 0.0), 1.0)
    pnl = float(payload.get("attributed_pnl") or 0.0)
    drawdown = max(float(payload.get("attributed_drawdown") or 0.0), 0.0)
    economics = pnl / max(abs(pnl) + drawdown, 1.0)
    return round(0.45 * accuracy + 0.35 * calibration + 0.20 * economics, 12)


def _digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


__all__ = ["AgentAttribution", "OutcomeAttributionService"]
