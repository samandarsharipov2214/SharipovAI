"""Persistent MetaAI state backed by the canonical SharipovAI ProjectDatabase."""

from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, datetime
from math import isfinite
from typing import Iterable, Mapping, Sequence

from meta_ai import AgentReputation, DecisionAudit, MetaAI, PredictionOutcome, VALID_REGIMES
from storage import ProjectDatabase, VersionConflict

STATE_SCHEMA_VERSION = 1
DEFAULT_ORGAN_ID = "decision_quality.meta_ai"
EVENT_NAMESPACE = "decision_quality"
VERIFIED_EVIDENCE_CLASSES = {
    "verified_market",
    "verified_exchange",
    "verified_bybit",
    "verified_market_and_news",
}


class MetaAIPersistenceError(RuntimeError):
    """Raised when persistent MetaAI state is missing, corrupt, or unsafe."""


class PersistentMetaAI(MetaAI):
    """MetaAI whose reputation and outcome history survive process restarts.

    The class intentionally requires a stable decision id for every persisted
    outcome batch. This prevents duplicate retries from inflating reputation.
    """

    def __init__(
        self,
        database: ProjectDatabase | None = None,
        *,
        organ_id: str = DEFAULT_ORGAN_ID,
        history_limit: int = 2_000,
    ) -> None:
        super().__init__()
        self.database = database or ProjectDatabase()
        self.organ_id = str(organ_id).strip()
        if not self.organ_id:
            raise ValueError("organ_id must not be empty")
        self.history_limit = min(max(int(history_limit), 1), 100_000)
        self._state_version = 0
        self._processed_decision_ids: list[str] = []
        self.database.initialize()
        self.reload()

    def reload(self) -> None:
        """Reload the canonical state and replace the in-memory snapshot."""

        row = self.database.get_ai_state(self.organ_id)
        if row is None:
            self._state_version = 0
            self._processed_decision_ids = []
            self._reputations = {}
            self._history = []
            return
        state = row.get("state")
        if not isinstance(state, Mapping):
            raise MetaAIPersistenceError("MetaAI state must be a mapping")
        self._restore_state(state)
        self._state_version = int(row["version"])

    def record_outcomes(
        self,
        outcomes: Iterable[PredictionOutcome],
        *,
        decision_id: str | None = None,
        evidence_class: str = "verified_market",
        verified_market_data: bool = True,
    ) -> bool:
        """Persist one idempotent, verified batch of realized outcomes.

        Returns ``False`` when the same decision id has already been recorded.
        Unsafe or synthetic evidence is rejected instead of silently training
        the reputation model.
        """

        clean_id = str(decision_id or "").strip()
        if not clean_id:
            raise MetaAIPersistenceError("decision_id is required for persistent outcomes")
        if not verified_market_data or evidence_class not in VERIFIED_EVIDENCE_CLASSES:
            raise MetaAIPersistenceError("only verified market evidence may update AI reputation")
        if self._was_processed(clean_id):
            return False

        materialized = tuple(outcomes)
        if not materialized:
            raise MetaAIPersistenceError("at least one PredictionOutcome is required")

        before = self._state_payload()
        super().record_outcomes(materialized)
        self._processed_decision_ids.append(clean_id)
        self._processed_decision_ids = self._processed_decision_ids[-self.history_limit :]

        try:
            new_version = self.database.set_ai_state(
                self.organ_id,
                self._state_payload(),
                expected_version=self._state_version,
            )
        except Exception:
            self._restore_state(before)
            raise

        self._state_version = new_version
        self.database.append_event(
            EVENT_NAMESPACE,
            "meta_outcome",
            clean_id,
            {
                "organ_id": self.organ_id,
                "decision_id": clean_id,
                "evidence_class": evidence_class,
                "verified_market_data": True,
                "outcomes": [_outcome_payload(item) for item in materialized],
                "state_version": new_version,
            },
            event_id=f"meta-outcome-{clean_id}",
        )
        return True

    def audit_and_persist(
        self,
        decision_id: str,
        opinions: Sequence,
        *,
        selected_action: str,
        realized_action: str,
    ) -> DecisionAudit:
        """Create and append an immutable post-decision audit event."""

        clean_id = str(decision_id).strip()
        if not clean_id:
            raise MetaAIPersistenceError("decision_id is required for audit persistence")
        existing = self.database.list_events(
            EVENT_NAMESPACE,
            entity_type="decision_audit",
            entity_id=clean_id,
            limit=1,
        )
        if existing:
            payload = existing[0]["payload"].get("audit")
            return _audit_from_payload(payload)

        audit = self.audit_decision(
            opinions,
            selected_action=selected_action,
            realized_action=realized_action,
        )
        self.database.append_event(
            EVENT_NAMESPACE,
            "decision_audit",
            clean_id,
            {
                "organ_id": self.organ_id,
                "decision_id": clean_id,
                "audit": asdict(audit),
                "state_version": self._state_version,
            },
            event_id=f"meta-audit-{clean_id}",
        )
        return audit

    def persistence_status(self) -> dict[str, object]:
        return {
            "organ_id": self.organ_id,
            "state_version": self._state_version,
            "agents": len(self._reputations),
            "history_records": len(self._history),
            "processed_decisions": len(self._processed_decision_ids),
            "database_backend": self.database.backend,
        }

    def _was_processed(self, decision_id: str) -> bool:
        if decision_id in self._processed_decision_ids:
            return True
        return bool(
            self.database.list_events(
                EVENT_NAMESPACE,
                entity_type="meta_outcome",
                entity_id=decision_id,
                limit=1,
            )
        )

    def _state_payload(self) -> dict[str, object]:
        reputations = {
            agent_id: {
                "agent_id": rep.agent_id,
                "total_predictions": rep.total_predictions,
                "correct_predictions": rep.correct_predictions,
                "confidence_error_sum": rep.confidence_error_sum,
                "pnl_contribution": rep.pnl_contribution,
                "drawdown_contribution": rep.drawdown_contribution,
                "regime_total": dict(rep.regime_total),
                "regime_correct": dict(rep.regime_correct),
            }
            for agent_id, rep in sorted(self._reputations.items())
        }
        history = [_outcome_payload(item) for item in self._history[-self.history_limit :]]
        return {
            "schema_version": STATE_SCHEMA_VERSION,
            "saved_at": datetime.now(UTC).isoformat(),
            "processed_decision_ids": self._processed_decision_ids[-self.history_limit :],
            "reputations": reputations,
            "history": history,
        }

    def _restore_state(self, state: Mapping[str, object]) -> None:
        schema_version = _non_negative_int(state.get("schema_version"), "schema_version")
        if schema_version != STATE_SCHEMA_VERSION:
            raise MetaAIPersistenceError(
                f"unsupported MetaAI state schema {schema_version}; expected {STATE_SCHEMA_VERSION}"
            )

        raw_reputations = state.get("reputations", {})
        raw_history = state.get("history", [])
        raw_ids = state.get("processed_decision_ids", [])
        if not isinstance(raw_reputations, Mapping):
            raise MetaAIPersistenceError("reputations must be a mapping")
        if not isinstance(raw_history, list):
            raise MetaAIPersistenceError("history must be a list")
        if not isinstance(raw_ids, list):
            raise MetaAIPersistenceError("processed_decision_ids must be a list")

        reputations: dict[str, AgentReputation] = {}
        for key, raw in raw_reputations.items():
            if not isinstance(raw, Mapping):
                raise MetaAIPersistenceError(f"invalid reputation payload for {key}")
            agent_id = str(raw.get("agent_id") or key).strip()
            if not agent_id:
                raise MetaAIPersistenceError("agent_id must not be empty")
            total = _non_negative_int(raw.get("total_predictions"), "total_predictions")
            correct = _non_negative_int(raw.get("correct_predictions"), "correct_predictions")
            if correct > total:
                raise MetaAIPersistenceError("correct_predictions cannot exceed total_predictions")
            regime_total = _count_map(raw.get("regime_total", {}), "regime_total")
            regime_correct = _count_map(raw.get("regime_correct", {}), "regime_correct")
            for regime, count in regime_correct.items():
                if count > regime_total.get(regime, 0):
                    raise MetaAIPersistenceError("regime_correct cannot exceed regime_total")
            reputations[agent_id] = AgentReputation(
                agent_id=agent_id,
                total_predictions=total,
                correct_predictions=correct,
                confidence_error_sum=_finite_float(
                    raw.get("confidence_error_sum"), "confidence_error_sum", minimum=0.0
                ),
                pnl_contribution=_finite_float(raw.get("pnl_contribution"), "pnl_contribution"),
                drawdown_contribution=_finite_float(
                    raw.get("drawdown_contribution"), "drawdown_contribution", minimum=0.0
                ),
                regime_total=regime_total,
                regime_correct=regime_correct,
            )

        history = [_outcome_from_payload(item) for item in raw_history[-self.history_limit :]]
        processed_ids = [str(item).strip() for item in raw_ids[-self.history_limit :]]
        if any(not item for item in processed_ids):
            raise MetaAIPersistenceError("processed decision ids must not be empty")

        self._reputations = reputations
        self._history = history
        self._processed_decision_ids = processed_ids


def _outcome_payload(outcome: PredictionOutcome) -> dict[str, object]:
    return {
        "agent_id": outcome.agent_id,
        "predicted_action": outcome.predicted_action,
        "realized_action": outcome.realized_action,
        "confidence": outcome.confidence,
        "pnl_contribution": outcome.pnl_contribution,
        "drawdown_contribution": outcome.drawdown_contribution,
        "regime": outcome.regime,
        "timestamp": outcome.timestamp.astimezone(UTC).isoformat(),
    }


def _outcome_from_payload(raw: object) -> PredictionOutcome:
    if not isinstance(raw, Mapping):
        raise MetaAIPersistenceError("history outcome must be a mapping")
    regime = str(raw.get("regime", "unknown"))
    if regime not in VALID_REGIMES:
        raise MetaAIPersistenceError(f"unsupported stored regime: {regime}")
    try:
        timestamp = datetime.fromisoformat(str(raw.get("timestamp")))
    except (TypeError, ValueError) as exc:
        raise MetaAIPersistenceError("invalid stored outcome timestamp") from exc
    if timestamp.tzinfo is None:
        raise MetaAIPersistenceError("stored outcome timestamp must be timezone-aware")
    return PredictionOutcome(
        agent_id=str(raw.get("agent_id", "")).strip(),
        predicted_action=str(raw.get("predicted_action", "")).strip(),
        realized_action=str(raw.get("realized_action", "")).strip(),
        confidence=_finite_float(raw.get("confidence"), "confidence", minimum=0.0, maximum=1.0),
        pnl_contribution=_finite_float(raw.get("pnl_contribution"), "pnl_contribution"),
        drawdown_contribution=_finite_float(
            raw.get("drawdown_contribution"), "drawdown_contribution", minimum=0.0
        ),
        regime=regime,
        timestamp=timestamp.astimezone(UTC),
    )


def _audit_from_payload(raw: object) -> DecisionAudit:
    if not isinstance(raw, Mapping):
        raise MetaAIPersistenceError("stored audit must be a mapping")
    return DecisionAudit(
        selected_action=str(raw.get("selected_action", "")),
        realized_action=str(raw.get("realized_action", "")),
        winning_agents=tuple(str(item) for item in raw.get("winning_agents", [])),
        losing_agents=tuple(str(item) for item in raw.get("losing_agents", [])),
        abstaining_agents=tuple(str(item) for item in raw.get("abstaining_agents", [])),
        confidence_gap=_finite_float(raw.get("confidence_gap"), "confidence_gap"),
        lessons=tuple(str(item) for item in raw.get("lessons", [])),
    )


def _count_map(raw: object, name: str) -> dict[str, int]:
    if not isinstance(raw, Mapping):
        raise MetaAIPersistenceError(f"{name} must be a mapping")
    result: dict[str, int] = {}
    for regime, value in raw.items():
        clean_regime = str(regime)
        if clean_regime not in VALID_REGIMES:
            raise MetaAIPersistenceError(f"unsupported regime in {name}: {clean_regime}")
        result[clean_regime] = _non_negative_int(value, f"{name}.{clean_regime}")
    return result


def _non_negative_int(value: object, name: str) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise MetaAIPersistenceError(f"{name} must be an integer") from exc
    if parsed < 0:
        raise MetaAIPersistenceError(f"{name} must be non-negative")
    return parsed


def _finite_float(
    value: object,
    name: str,
    *,
    minimum: float | None = None,
    maximum: float | None = None,
) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise MetaAIPersistenceError(f"{name} must be numeric") from exc
    if not isfinite(parsed):
        raise MetaAIPersistenceError(f"{name} must be finite")
    if minimum is not None and parsed < minimum:
        raise MetaAIPersistenceError(f"{name} must be >= {minimum}")
    if maximum is not None and parsed > maximum:
        raise MetaAIPersistenceError(f"{name} must be <= {maximum}")
    return parsed


__all__ = [
    "DEFAULT_ORGAN_ID",
    "EVENT_NAMESPACE",
    "MetaAIPersistenceError",
    "PersistentMetaAI",
    "STATE_SCHEMA_VERSION",
    "VERIFIED_EVIDENCE_CLASSES",
    "VersionConflict",
]
