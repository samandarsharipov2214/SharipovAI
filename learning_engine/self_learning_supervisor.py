"""Restart-safe supervisor that converts settled Paper outcomes into learning evidence."""
from __future__ import annotations

import os
import threading
import time
from typing import Any, Mapping

from meta_ai_persistence import EVENT_NAMESPACE
from storage import ProjectDatabase, list_json_items

from .development_learning import DevelopmentLearningService
from .outcome_attribution import OutcomeAttributionService
from .research_challengers import ResearchChallengerService

_SETTLEMENT_NAMESPACE = "paper_decision_settlements"
_STATE_NAMESPACE = "self_learning_supervisor_state"
_TRUE = {"1", "true", "yes", "on"}


class SelfLearningSupervisor:
    def __init__(
        self,
        database: ProjectDatabase | None = None,
        *,
        attribution: OutcomeAttributionService | None = None,
        challengers: ResearchChallengerService | None = None,
        development_learning: DevelopmentLearningService | None = None,
    ) -> None:
        self.database = database or ProjectDatabase()
        self.database.initialize()
        self.attribution = attribution or OutcomeAttributionService(self.database)
        self.challengers = challengers or ResearchChallengerService(self.database)
        self.development_learning = development_learning or DevelopmentLearningService(self.database)
        self.interval_seconds = _bounded_float("SELF_LEARNING_INTERVAL_SECONDS", 60.0, 5.0, 3600.0)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def enabled(self) -> bool:
        return os.getenv("SELF_LEARNING_ENABLED", "0").strip().lower() in _TRUE

    def run_once(self, *, now_ms: int | None = None) -> dict[str, Any]:
        timestamp = int(time.time() * 1000) if now_ms is None else int(now_ms)
        if timestamp <= 0:
            raise ValueError("now_ms must be positive")
        processed = skipped = failed = 0
        errors: list[str] = []
        settlements = list_json_items(
            self.database,
            _SETTLEMENT_NAMESPACE,
            limit=10_000,
            newest_first=False,
        )
        for row in settlements:
            settlement = row.get("value")
            if not isinstance(settlement, Mapping):
                failed += 1
                errors.append(f"invalid settlement payload: {row.get('key')}")
                continue
            decision_id = str(settlement.get("decision_id") or row.get("key") or "").strip()
            if not decision_id:
                failed += 1
                errors.append("settlement without decision_id")
                continue
            outcome_id = f"paper:{decision_id}"
            if self.attribution.get(outcome_id) is not None:
                skipped += 1
                continue
            try:
                evidence = self._evidence_from_settlement(decision_id, settlement, timestamp)
                self.attribution.record(evidence)
                processed += 1
            except (KeyError, RuntimeError, TypeError, ValueError, OSError) as exc:
                failed += 1
                errors.append(f"{decision_id}: {type(exc).__name__}: {exc}")

        summary = self.attribution.summary()
        summary["agents"] = self.attribution.agent_metrics(limit=10_000)
        challenger_result: dict[str, Any] = {}
        source_experiment = os.getenv("SELF_LEARNING_SOURCE_EXPERIMENT_ID", "").strip()
        if source_experiment:
            try:
                evaluation = self.challengers.evaluate_learning_summary(summary)
                if evaluation.eligible:
                    challenger_result = self.challengers.create(
                        scope=os.getenv("SELF_LEARNING_RESEARCH_SCOPE", "global.paper"),
                        source_experiment_id=source_experiment,
                        strategy_config_patch={
                            "agent_learning_scores": {
                                str(item.get("agent_id")): float(item.get("learning_score") or 0.0)
                                for item in summary["agents"]
                            },
                            "self_learning_evidence_sha256": _summary_digest(summary),
                        },
                        learning_summary=summary,
                        now_ms=timestamp,
                    )
                else:
                    challenger_result = {
                        "status": "insufficient_evidence",
                        "evaluation": evaluation.to_dict(),
                    }
            except (KeyError, RuntimeError, TypeError, ValueError, OSError) as exc:
                challenger_result = {
                    "status": "blocked",
                    "error": f"{type(exc).__name__}: {exc}",
                }

        try:
            development_result = self.development_learning.run_weekly_process_review(timestamp)
        except (KeyError, RuntimeError, TypeError, ValueError, OSError) as exc:
            development_result = {
                "status": "blocked",
                "proposal_type": "process_optimization",
                "error": f"{type(exc).__name__}: {exc}",
                "requires_manual_approval": True,
                "execution_authority": False,
                "automatic_code_application": False,
                "runtime_flags_changed": False,
            }

        state = {
            "status": "degraded" if failed or development_result.get("status") in {"blocked", "error"} else "ok",
            "processed_count": processed,
            "skipped_count": skipped,
            "failed_count": failed,
            "errors": errors[-20:],
            "learning_summary": summary,
            "challenger": challenger_result,
            "development_learning": development_result,
            "updated_at_ms": timestamp,
            "execution_authority": False,
            "automatic_execution_promotion": False,
            "runtime_flags_changed": False,
        }
        current = self.database.get_json(_STATE_NAMESPACE, "current")
        self.database.put_json(
            _STATE_NAMESPACE,
            "current",
            state,
            expected_version=int(current["version"]) if current else 0,
        )
        return state

    def status(self) -> dict[str, Any]:
        current = self.database.get_json(_STATE_NAMESPACE, "current")
        state = dict(current["value"]) if current else {"status": "not_run", "updated_at_ms": 0}
        return {
            **state,
            "enabled": self.enabled(),
            "worker_running": bool(self._thread and self._thread.is_alive()),
            "interval_seconds": self.interval_seconds,
            "execution_authority": False,
            "automatic_execution_promotion": False,
        }

    def start(self) -> None:
        if not self.enabled() or (self._thread and self._thread.is_alive()):
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="self-learning-supervisor", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5.0)

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.run_once()
            except Exception as exc:  # pragma: no cover - production containment
                current = self.database.get_json(_STATE_NAMESPACE, "current")
                payload = {
                    "status": "error",
                    "error": f"{type(exc).__name__}: {exc}",
                    "updated_at_ms": int(time.time() * 1000),
                    "execution_authority": False,
                    "automatic_execution_promotion": False,
                    "runtime_flags_changed": False,
                }
                self.database.put_json(
                    _STATE_NAMESPACE,
                    "current",
                    payload,
                    expected_version=int(current["version"]) if current else 0,
                )
            self._stop.wait(self.interval_seconds)

    def _evidence_from_settlement(
        self,
        decision_id: str,
        settlement: Mapping[str, Any],
        fallback_timestamp: int,
    ) -> dict[str, Any]:
        events = self.database.list_events(
            EVENT_NAMESPACE,
            entity_type="decision_assessment",
            entity_id=decision_id,
            limit=1,
        )
        if not events:
            raise ValueError("decision assessment evidence is missing")
        payload = events[0].get("payload")
        if not isinstance(payload, Mapping):
            raise ValueError("decision assessment payload is invalid")
        opinions = payload.get("opinions")
        if not isinstance(opinions, list) or not opinions:
            raise ValueError("decision assessment opinions are missing")
        assessment = payload.get("assessment") if isinstance(payload.get("assessment"), Mapping) else {}
        evidence_class, verified_market_data = _require_verified_settlement_evidence(settlement)
        return {
            "outcome_id": f"paper:{decision_id}",
            "decision_id": decision_id,
            "source": "paper",
            "selected_action": settlement.get("selected_action") or assessment.get("action") or "WAIT",
            "realized_action": settlement.get("realized_action") or "HOLD",
            "net_pnl": settlement.get("net_pnl"),
            "drawdown_contribution": settlement.get("drawdown_contribution", 0.0),
            "regime": assessment.get("regime") or "unknown",
            "agents": _agents_with_settlement_attestation(opinions, evidence_class, verified_market_data),
            "occurred_at_ms": int(settlement.get("settled_at_ms") or events[0].get("created_at_ms") or fallback_timestamp),
            "evidence_class": evidence_class,
            "verified_market_data": verified_market_data,
        }


_VERIFIED_EVIDENCE_CLASSES = {
    "verified_market",
    "verified_exchange",
    "verified_bybit",
    "verified_market_and_news",
}
_FORBIDDEN_EVIDENCE_CLASSES = {"synthetic", "fixture", "mock", "demo", "simulation"}


def _require_verified_settlement_evidence(settlement: Mapping[str, Any]) -> tuple[str, bool]:
    """Fail closed: attestation requires an explicit supported verified settlement class.

    Missing, blank, unsupported, synthetic/demo/mock/fixture/simulation, or
    non-True verified_market_data must not default to a verified class.
    """

    raw_class = settlement.get("evidence_class") if "evidence_class" in settlement else None
    if raw_class is None:
        raise ValueError("settlement evidence_class is required")
    evidence_class = str(raw_class).strip().lower()
    if not evidence_class:
        raise ValueError("settlement evidence_class is required")
    if evidence_class in _FORBIDDEN_EVIDENCE_CLASSES:
        raise ValueError(f"synthetic settlement evidence is forbidden: {evidence_class}")
    if evidence_class not in _VERIFIED_EVIDENCE_CLASSES:
        raise ValueError(f"unsupported settlement evidence_class: {evidence_class}")
    if settlement.get("verified_market_data") is not True:
        raise ValueError("verified market evidence is required")
    return evidence_class, True


def _agents_with_settlement_attestation(
    opinions: list[Any],
    settlement_evidence_class: str,
    settlement_verified_market_data: bool,
) -> list[dict[str, Any]]:
    """Attach settlement market attestation to stripped council opinions fail-closed.

    Decision-assessment opinions are stored without evidence_class after DQ
    evaluate. When the paper settlement itself proves verified market evidence,
    re-attach that attestation so AgentEvidence can accept the organ opinions.
    Synthetic, unsupported, or unverified settlements/opinions are left untouched
    so the validator still rejects them.
    """

    settlement_attests = (
        settlement_verified_market_data is True
        and settlement_evidence_class in _VERIFIED_EVIDENCE_CLASSES
        and settlement_evidence_class not in _FORBIDDEN_EVIDENCE_CLASSES
    )
    agents: list[dict[str, Any]] = []
    for item in opinions:
        if not isinstance(item, Mapping):
            continue
        agent = dict(item)
        existing_class = str(agent.get("evidence_class") or "").strip().lower()
        if existing_class in _FORBIDDEN_EVIDENCE_CLASSES:
            agents.append(agent)
            continue
        if agent.get("verified_market_data") is False or agent.get("data_verified") is False:
            agents.append(agent)
            continue
        if existing_class in _VERIFIED_EVIDENCE_CLASSES and agent.get("verified_market_data") is True:
            agents.append(agent)
            continue
        if not settlement_attests:
            agents.append(agent)
            continue
        if not existing_class:
            agent["evidence_class"] = settlement_evidence_class
        elif existing_class not in _VERIFIED_EVIDENCE_CLASSES:
            agents.append(agent)
            continue
        agent["verified_market_data"] = True
        agents.append(agent)
    return agents



def _bounded_float(name: str, default: float, minimum: float, maximum: float) -> float:
    try:
        value = float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        value = default
    if value != value or value in {float("inf"), float("-inf")}:
        value = default
    return min(max(value, minimum), maximum)


def _summary_digest(value: Mapping[str, Any]) -> str:
    import hashlib
    import json

    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    ).hexdigest()


__all__ = ["SelfLearningSupervisor"]
