"""Evidence-gated champion/challenger leadership without automatic deployment."""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import asdict, dataclass
from typing import Any, Mapping

from storage import ProjectDatabase, VersionConflict

from .registry import ExperimentRegistry

_NAMESPACE = "strategy_leadership"
_EVENT_NAMESPACE = "strategy_leadership_events"


@dataclass(frozen=True, slots=True)
class LeadershipDecision:
    scope: str
    champion_experiment_id: str
    previous_champion_experiment_id: str
    target_stage: str
    actor: str
    reason: str
    evidence_sha256: str
    decided_at_ms: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ChampionChallengerRegistry:
    """Maintain exactly one evidence-approved champion per bounded strategy scope."""

    def __init__(
        self,
        database: ProjectDatabase | None = None,
        *,
        experiments: ExperimentRegistry | None = None,
    ) -> None:
        self.database = database or ProjectDatabase()
        self.database.initialize()
        self.experiments = experiments or ExperimentRegistry(self.database)

    def snapshot(self, scope: str) -> dict[str, Any]:
        clean_scope = _identifier(scope, "scope")
        current = self.database.get_json(_NAMESPACE, clean_scope)
        if current is None:
            return {
                "scope": clean_scope,
                "champion_experiment_id": "",
                "challengers": {},
                "history": [],
                "version": 0,
                "runtime_deployment_changed": False,
            }
        return {
            **dict(current["value"]),
            "version": int(current["version"]),
            "database_updated_at_ms": int(current["updated_at_ms"]),
            "runtime_deployment_changed": False,
        }

    def register_challenger(
        self,
        scope: str,
        experiment_id: str,
        *,
        actor: str,
        reason: str,
        expected_version: int | None = None,
        now_ms: int | None = None,
    ) -> dict[str, Any]:
        clean_scope = _identifier(scope, "scope")
        clean_experiment = _identifier(experiment_id, "experiment_id")
        clean_actor = _identifier(actor, "actor")
        clean_reason = _text(reason, "reason")
        experiment = self._experiment(clean_experiment)
        if str(experiment.get("status")) not in {
            "completed",
            "promotion_pending",
            "promoted",
            "rejected",
        }:
            raise ValueError("challenger requires completed research evidence")
        timestamp = _timestamp(now_ms)
        current = self.snapshot(clean_scope)
        version = int(current["version"])
        _expected(expected_version, version, clean_scope)
        if current.get("champion_experiment_id") == clean_experiment:
            raise ValueError("current champion cannot also be registered as challenger")
        challengers = dict(current.get("challengers") or {})
        if clean_experiment in challengers:
            raise ValueError("experiment is already registered as challenger")
        challengers[clean_experiment] = {
            "experiment_id": clean_experiment,
            "strategy_name": experiment.get("strategy_name"),
            "status": "active",
            "registered_at_ms": timestamp,
            "actor": clean_actor,
            "reason": clean_reason,
            "commit_sha": experiment.get("commit_sha"),
            "manifest": experiment.get("manifest"),
        }
        payload = {
            "scope": clean_scope,
            "champion_experiment_id": str(current.get("champion_experiment_id") or ""),
            "challengers": challengers,
            "history": list(current.get("history") or [])[-100:],
            "updated_at_ms": timestamp,
        }
        new_version = self.database.put_json(
            _NAMESPACE,
            clean_scope,
            payload,
            expected_version=version,
        )
        event_id = self._event(
            clean_scope,
            "challenger_registered",
            {
                "experiment_id": clean_experiment,
                "actor": clean_actor,
                "reason": clean_reason,
                "version": new_version,
            },
            timestamp,
        )
        return {**payload, "version": new_version, "event_id": event_id}

    def promote_challenger(
        self,
        scope: str,
        experiment_id: str,
        *,
        target_stage: str,
        actor: str,
        reason: str,
        expected_version: int | None = None,
        approval_token: str,
        now_ms: int | None = None,
    ) -> dict[str, Any]:
        clean_scope = _identifier(scope, "scope")
        clean_experiment = _identifier(experiment_id, "experiment_id")
        clean_stage = _identifier(target_stage, "target_stage")
        clean_actor = _identifier(actor, "actor")
        clean_reason = _text(reason, "reason")
        expected_token = f"PROMOTE:{clean_scope}:{clean_experiment}:{clean_stage}"
        if approval_token != expected_token:
            raise ValueError("leadership approval token does not match scope/experiment/stage")
        experiment = self._experiment(clean_experiment)
        _require_promotion_evidence(experiment, clean_stage)
        timestamp = _timestamp(now_ms)
        current = self.snapshot(clean_scope)
        version = int(current["version"])
        _expected(expected_version, version, clean_scope)
        challengers = dict(current.get("challengers") or {})
        if clean_experiment not in challengers:
            raise ValueError("experiment is not an active challenger in this scope")
        if str(challengers[clean_experiment].get("status")) != "active":
            raise ValueError("challenger is not active")
        previous = str(current.get("champion_experiment_id") or "")
        evidence = {
            "experiment_id": clean_experiment,
            "target_stage": clean_stage,
            "promotion": experiment.get("promotion"),
            "commit_sha": experiment.get("commit_sha"),
            "manifest": experiment.get("manifest"),
            "results": experiment.get("results"),
        }
        evidence_sha = _digest(evidence)
        challengers[clean_experiment] = {
            **dict(challengers[clean_experiment]),
            "status": "promoted_to_champion",
            "promoted_at_ms": timestamp,
        }
        if previous and previous != clean_experiment:
            challengers[previous] = {
                "experiment_id": previous,
                "status": "retired_champion",
                "retired_at_ms": timestamp,
                "replaced_by": clean_experiment,
            }
        decision = LeadershipDecision(
            scope=clean_scope,
            champion_experiment_id=clean_experiment,
            previous_champion_experiment_id=previous,
            target_stage=clean_stage,
            actor=clean_actor,
            reason=clean_reason,
            evidence_sha256=evidence_sha,
            decided_at_ms=timestamp,
        )
        history = [*list(current.get("history") or []), decision.to_dict()][-100:]
        payload = {
            "scope": clean_scope,
            "champion_experiment_id": clean_experiment,
            "challengers": challengers,
            "history": history,
            "last_decision": decision.to_dict(),
            "updated_at_ms": timestamp,
            "runtime_deployment_changed": False,
        }
        new_version = self.database.put_json(
            _NAMESPACE,
            clean_scope,
            payload,
            expected_version=version,
        )
        event_id = self._event(
            clean_scope,
            "champion_promoted",
            {**decision.to_dict(), "version": new_version},
            timestamp,
        )
        return {**payload, "version": new_version, "event_id": event_id}

    def comparison(self, scope: str) -> dict[str, Any]:
        snapshot = self.snapshot(scope)
        identifiers = [
            str(snapshot.get("champion_experiment_id") or ""),
            *[
                identifier
                for identifier, item in dict(snapshot.get("challengers") or {}).items()
                if str(item.get("status")) == "active"
            ],
        ]
        unique = [item for index, item in enumerate(identifiers) if item and item not in identifiers[:index]]
        if len(unique) < 2:
            return {
                "status": "insufficient_candidates",
                "scope": snapshot["scope"],
                "experiment_ids": unique,
            }
        return {"scope": snapshot["scope"], **self.experiments.compare(unique)}

    def _experiment(self, experiment_id: str) -> dict[str, Any]:
        experiment = self.experiments.get(experiment_id)
        if experiment is None:
            raise KeyError(experiment_id)
        return experiment

    def _event(
        self,
        scope: str,
        action: str,
        payload: Mapping[str, Any],
        timestamp: int,
    ) -> str:
        return self.database.append_event(
            _EVENT_NAMESPACE,
            "strategy_scope",
            scope,
            {"action": action, **dict(payload)},
            created_at_ms=timestamp,
        )


def _require_promotion_evidence(experiment: Mapping[str, Any], target_stage: str) -> None:
    if str(experiment.get("status")) != "promoted":
        raise ValueError("champion promotion requires a promoted experiment")
    promotion = experiment.get("promotion")
    if not isinstance(promotion, Mapping):
        raise ValueError("experiment promotion evidence is missing")
    if str(promotion.get("status")) != "approved":
        raise ValueError("experiment manual promotion is not approved")
    if str(promotion.get("target_stage")) != target_stage:
        raise ValueError("experiment promotion stage does not match leadership target")
    report = promotion.get("report")
    manual = promotion.get("manual_decision")
    if not isinstance(report, Mapping) or not bool(report.get("automated_gate_passed")):
        raise ValueError("automated promotion gates did not pass")
    if not isinstance(manual, Mapping) or not bool(manual.get("approved")):
        raise ValueError("manual experiment approval is missing")
    if report.get("failed_gates"):
        raise ValueError("promotion report contains failed gates")


def _expected(expected: int | None, current: int, scope: str) -> None:
    if expected is not None and int(expected) != current:
        raise VersionConflict(
            f"version mismatch for strategy scope {scope}: expected {expected}, current {current}"
        )


def _identifier(value: Any, name: str) -> str:
    clean = str(value or "").strip()
    if not clean or len(clean) > 200:
        raise ValueError(f"invalid {name}")
    if any(character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.:-" for character in clean):
        raise ValueError(f"invalid {name}")
    return clean


def _text(value: Any, name: str) -> str:
    clean = str(value or "").strip()
    if not clean or len(clean) > 4_000:
        raise ValueError(f"invalid {name}")
    return clean


def _timestamp(value: int | None) -> int:
    parsed = int(time.time() * 1000) if value is None else int(value)
    if parsed <= 0:
        raise ValueError("timestamp must be positive")
    return parsed


def _digest(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


__all__ = ["ChampionChallengerRegistry", "LeadershipDecision"]
