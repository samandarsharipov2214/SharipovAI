"""Persistent MetaAI state backed by the canonical SharipovAI ProjectDatabase."""
from __future__ import annotations

import json
import time
from dataclasses import asdict
from datetime import UTC, datetime
from math import isfinite
from typing import Iterable, Mapping, Sequence

from meta_ai import (
    AgentReputation,
    DecisionAudit,
    MetaAI,
    PredictionOutcome,
    VALID_ACTIONS,
    VALID_REGIMES,
)
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

    State and its immutable ``meta_outcome`` event are written in one database
    transaction. A stable decision id makes retries idempotent and any mismatch
    between state and events blocks the component fail-closed.
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
        self.history_limit = min(max(_positive_int(history_limit, "history_limit"), 1), 100_000)
        self._state_version = 0
        self._processed_decision_ids: list[str] = []
        self.database.initialize()
        self.reload()

    def reload(self) -> None:
        """Reload canonical state and verify its immutable outcome evidence."""

        row = self.database.get_ai_state(self.organ_id)
        if row is None:
            events = self.database.list_events(
                EVENT_NAMESPACE,
                entity_type="meta_outcome",
                limit=1,
            )
            if events:
                raise MetaAIPersistenceError("MetaAI outcome events exist without canonical AI state")
            self._state_version = 0
            self._processed_decision_ids = []
            self._reputations = {}
            self._history = []
            return
        state = row.get("state")
        if not isinstance(state, Mapping):
            raise MetaAIPersistenceError("MetaAI state must be a mapping")
        self._restore_state(state)
        self._state_version = _positive_int(row.get("version"), "state version")
        self._verify_state_event_consistency()

    def record_outcomes(
        self,
        outcomes: Iterable[PredictionOutcome],
        *,
        decision_id: str | None = None,
        evidence_class: str = "verified_market",
        verified_market_data: bool = True,
    ) -> bool:
        """Atomically persist one idempotent, verified batch of outcomes."""

        clean_id = _decision_id(decision_id)
        normalized_class = str(evidence_class or "").strip().lower()
        if verified_market_data is not True or normalized_class not in VERIFIED_EVIDENCE_CLASSES:
            raise MetaAIPersistenceError("only verified market evidence may update AI reputation")
        if self._was_processed(clean_id):
            return False

        materialized = tuple(outcomes)
        if not materialized:
            raise MetaAIPersistenceError("at least one PredictionOutcome is required")
        if not all(isinstance(item, PredictionOutcome) for item in materialized):
            raise MetaAIPersistenceError("outcomes must contain PredictionOutcome values")

        before = self._state_payload()
        before_version = self._state_version
        super().record_outcomes(materialized)
        self._processed_decision_ids.append(clean_id)
        self._processed_decision_ids = self._processed_decision_ids[-self.history_limit :]

        try:
            new_version = self._atomic_state_and_outcome_event(
                clean_id,
                normalized_class,
                materialized,
            )
        except Exception:
            self._restore_state(before)
            self._state_version = before_version
            try:
                self.reload()
            except Exception:
                raise
            if self._was_processed(clean_id):
                return False
            raise

        self._state_version = new_version
        return True

    def audit_and_persist(
        self,
        decision_id: str,
        opinions: Sequence,
        *,
        selected_action: str,
        realized_action: str,
    ) -> DecisionAudit:
        """Create and append one immutable post-decision audit event."""

        clean_id = _decision_id(decision_id)
        existing = self.database.list_events(
            EVENT_NAMESPACE,
            entity_type="decision_audit",
            entity_id=clean_id,
            limit=2,
        )
        if len(existing) > 1:
            raise MetaAIPersistenceError("duplicate decision audit events detected")
        if existing:
            event_payload = existing[0].get("payload")
            if not isinstance(event_payload, Mapping):
                raise MetaAIPersistenceError("stored decision audit event is invalid")
            if event_payload.get("organ_id") != self.organ_id or event_payload.get("decision_id") != clean_id:
                raise MetaAIPersistenceError("stored decision audit ownership is invalid")
            return _audit_from_payload(event_payload.get("audit"))

        audit = self.audit_decision(
            opinions,
            selected_action=selected_action,
            realized_action=realized_action,
        )
        payload = {
            "organ_id": self.organ_id,
            "decision_id": clean_id,
            "audit": asdict(audit),
            "state_version": self._state_version,
            "execution_authority": False,
        }
        try:
            self.database.append_event(
                EVENT_NAMESPACE,
                "decision_audit",
                clean_id,
                payload,
                event_id=f"meta-audit-{clean_id}",
            )
        except Exception:
            concurrent = self.database.list_events(
                EVENT_NAMESPACE,
                entity_type="decision_audit",
                entity_id=clean_id,
                limit=2,
            )
            if len(concurrent) == 1:
                stored = concurrent[0].get("payload")
                if isinstance(stored, Mapping):
                    return _audit_from_payload(stored.get("audit"))
            raise
        return audit

    def persistence_status(self) -> dict[str, object]:
        self._verify_state_event_consistency()
        return {
            "organ_id": self.organ_id,
            "state_version": self._state_version,
            "agents": len(self._reputations),
            "history_records": len(self._history),
            "processed_decisions": len(self._processed_decision_ids),
            "database_backend": self.database.backend,
            "atomic_state_event_writes": True,
            "evidence_consistent": True,
        }

    def _atomic_state_and_outcome_event(
        self,
        decision_id: str,
        evidence_class: str,
        outcomes: tuple[PredictionOutcome, ...],
    ) -> int:
        now_ms = int(time.time() * 1000)
        event_id = f"meta-outcome-{decision_id}"
        with self.database.connect() as connection:
            try:
                self.database._begin(connection, immediate=True)
                row = self.database._fetchone(
                    connection,
                    "SELECT version FROM ai_organ_state WHERE organ_id = ?",
                    (self.organ_id,),
                    lock=True,
                )
                current = int(row["version"]) if row else 0
                if current != self._state_version:
                    raise VersionConflict(
                        f"version mismatch for AI organ {self.organ_id}: expected {self._state_version}, current {current}"
                    )
                existing_event = self.database._fetchone(
                    connection,
                    "SELECT event_id FROM project_events WHERE event_id = ?",
                    (event_id,),
                    lock=True,
                )
                if existing_event is not None:
                    raise VersionConflict(f"outcome event already exists for {decision_id}")
                version = current + 1
                state_payload = self._state_payload()
                event_payload = {
                    "organ_id": self.organ_id,
                    "decision_id": decision_id,
                    "evidence_class": evidence_class,
                    "verified_market_data": True,
                    "outcomes": [_outcome_payload(item) for item in outcomes],
                    "state_version": version,
                    "execution_authority": False,
                }
                self.database._execute(
                    connection,
                    """
                    INSERT INTO ai_organ_state(organ_id, state_json, version, updated_at_ms)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(organ_id) DO UPDATE SET
                        state_json = excluded.state_json,
                        version = excluded.version,
                        updated_at_ms = excluded.updated_at_ms
                    """,
                    (self.organ_id, _json(state_payload), version, now_ms),
                )
                self.database._execute(
                    connection,
                    """
                    INSERT INTO project_events(event_id, namespace, entity_type, entity_id, payload_json, created_at_ms)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        event_id,
                        EVENT_NAMESPACE,
                        "meta_outcome",
                        decision_id,
                        _json(event_payload),
                        now_ms,
                    ),
                )
                connection.commit()
                return version
            except Exception:
                connection.rollback()
                raise

    def _was_processed(self, decision_id: str) -> bool:
        state_has = decision_id in self._processed_decision_ids
        events = self.database.list_events(
            EVENT_NAMESPACE,
            entity_type="meta_outcome",
            entity_id=decision_id,
            limit=2,
        )
        if len(events) > 1:
            raise MetaAIPersistenceError(f"duplicate outcome events detected for {decision_id}")
        event_has = len(events) == 1
        if state_has != event_has:
            raise MetaAIPersistenceError(f"MetaAI state/event mismatch for {decision_id}")
        if event_has:
            self._validate_outcome_event(events[0], decision_id)
        return state_has and event_has

    def _verify_state_event_consistency(self) -> None:
        ids = self._processed_decision_ids[-min(len(self._processed_decision_ids), 1000) :]
        events = self.database.list_events(
            EVENT_NAMESPACE,
            entity_type="meta_outcome",
            limit=max(1, min(max(len(ids), 1), 1000)),
        )
        event_ids: set[str] = set()
        for event in events:
            decision_id = str(event.get("entity_id") or "").strip()
            if not decision_id or decision_id in event_ids:
                raise MetaAIPersistenceError("duplicate or invalid MetaAI outcome event identity")
            self._validate_outcome_event(event, decision_id)
            event_ids.add(decision_id)
        state_ids = set(ids)
        if state_ids != event_ids:
            raise MetaAIPersistenceError("MetaAI state and immutable outcome events are inconsistent")

    def _validate_outcome_event(self, event: Mapping[str, object], decision_id: str) -> None:
        payload = event.get("payload")
        if not isinstance(payload, Mapping):
            raise MetaAIPersistenceError("MetaAI outcome event payload is invalid")
        if payload.get("organ_id") != self.organ_id or payload.get("decision_id") != decision_id:
            raise MetaAIPersistenceError("MetaAI outcome event ownership is invalid")
        if payload.get("verified_market_data") is not True:
            raise MetaAIPersistenceError("MetaAI outcome event is not verified")
        if str(payload.get("evidence_class") or "") not in VERIFIED_EVIDENCE_CLASSES:
            raise MetaAIPersistenceError("MetaAI outcome event evidence class is invalid")
        if payload.get("execution_authority") is not False:
            raise MetaAIPersistenceError("MetaAI outcome event must not have execution authority")
        if _positive_int(payload.get("state_version"), "outcome state_version") > self._state_version:
            raise MetaAIPersistenceError("MetaAI outcome event references a future state version")
        raw_outcomes = payload.get("outcomes")
        if not isinstance(raw_outcomes, list) or not raw_outcomes:
            raise MetaAIPersistenceError("MetaAI outcome event must contain outcomes")
        for raw in raw_outcomes:
            _outcome_from_payload(raw)

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
        try:
            saved_at = datetime.fromisoformat(str(state.get("saved_at")))
        except (TypeError, ValueError) as exc:
            raise MetaAIPersistenceError("MetaAI saved_at is invalid") from exc
        if saved_at.tzinfo is None:
            raise MetaAIPersistenceError("MetaAI saved_at must be timezone-aware")

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
        processed_ids = [_decision_id(item) for item in raw_ids[-self.history_limit :]]
        if len(processed_ids) != len(set(processed_ids)):
            raise MetaAIPersistenceError("processed decision ids must be unique")

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
    try:
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
    except (TypeError, ValueError) as exc:
        raise MetaAIPersistenceError(f"stored outcome is invalid: {exc}") from exc


def _audit_from_payload(raw: object) -> DecisionAudit:
    if not isinstance(raw, Mapping):
        raise MetaAIPersistenceError("stored audit must be a mapping")
    selected = str(raw.get("selected_action", "")).upper().strip()
    realized = str(raw.get("realized_action", "")).upper().strip()
    if selected not in VALID_ACTIONS or realized not in VALID_ACTIONS:
        raise MetaAIPersistenceError("stored audit actions are invalid")
    return DecisionAudit(
        selected_action=selected,
        realized_action=realized,
        winning_agents=_clean_tuple(raw.get("winning_agents", [])),
        losing_agents=_clean_tuple(raw.get("losing_agents", [])),
        abstaining_agents=_clean_tuple(raw.get("abstaining_agents", [])),
        confidence_gap=_finite_float(raw.get("confidence_gap"), "confidence_gap"),
        lessons=_clean_tuple(raw.get("lessons", [])),
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


def _decision_id(value: object) -> str:
    clean = str(value or "").strip()
    if not clean or len(clean) > 170 or not all(char.isalnum() or char in "._:-" for char in clean):
        raise MetaAIPersistenceError("decision_id is invalid")
    return clean


def _positive_int(value: object, name: str) -> int:
    parsed = _non_negative_int(value, name)
    if parsed <= 0:
        raise MetaAIPersistenceError(f"{name} must be positive")
    return parsed


def _non_negative_int(value: object, name: str) -> int:
    if isinstance(value, bool):
        raise MetaAIPersistenceError(f"{name} must be an integer")
    try:
        parsed_float = float(value)
    except (TypeError, ValueError) as exc:
        raise MetaAIPersistenceError(f"{name} must be an integer") from exc
    if not isfinite(parsed_float) or not parsed_float.is_integer():
        raise MetaAIPersistenceError(f"{name} must be an integer")
    parsed = int(parsed_float)
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
    if isinstance(value, bool):
        raise MetaAIPersistenceError(f"{name} must be numeric")
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


def _clean_tuple(raw: object) -> tuple[str, ...]:
    if not isinstance(raw, (list, tuple)):
        raise MetaAIPersistenceError("stored list field is invalid")
    result: list[str] = []
    for item in raw:
        clean = str(item).strip()
        if clean and clean not in result:
            result.append(clean)
    return tuple(result)


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True, allow_nan=False)


__all__ = [
    "DEFAULT_ORGAN_ID",
    "EVENT_NAMESPACE",
    "MetaAIPersistenceError",
    "PersistentMetaAI",
    "STATE_SCHEMA_VERSION",
    "VERIFIED_EVIDENCE_CLASSES",
    "VersionConflict",
]
