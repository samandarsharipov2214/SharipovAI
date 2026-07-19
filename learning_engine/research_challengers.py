"""Persistent challenger experiments and Paper-only research leadership."""
from __future__ import annotations

import hashlib
import json
import math
import time
from dataclasses import asdict, dataclass
from typing import Any, Mapping

from experiments import ExperimentRegistry
from storage import ProjectDatabase, list_json_items

from .evidence_policy import SelfLearningPolicy

_CHALLENGERS = "self_learning_challengers"
_LEADERSHIP = "self_learning_paper_leadership"
_EVENTS = "self_learning_challenger_events"


@dataclass(frozen=True, slots=True)
class ChallengerEvaluation:
    eligible: bool
    passed_gates: tuple[str, ...]
    failed_gates: tuple[str, ...]
    metrics: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ResearchChallengerService:
    def __init__(
        self,
        database: ProjectDatabase | None = None,
        *,
        experiments: ExperimentRegistry | None = None,
        policy: SelfLearningPolicy | None = None,
    ) -> None:
        self.database = database or ProjectDatabase()
        self.database.initialize()
        self.experiments = experiments or ExperimentRegistry(self.database)
        self.policy = policy or SelfLearningPolicy()

    def evaluate_learning_summary(self, summary: Mapping[str, Any]) -> ChallengerEvaluation:
        agents = summary.get("agents") if isinstance(summary.get("agents"), list) else []
        qualified = [
            row for row in agents
            if isinstance(row, Mapping)
            and int(row.get("outcome_count") or 0) >= self.policy.minimum_agent_outcomes
            and _number(row.get("direction_accuracy")) >= self.policy.minimum_direction_accuracy
            and _number(row.get("mean_confidence_error")) <= self.policy.maximum_calibration_error
        ]
        metrics = {
            "outcome_count": int(summary.get("verified_outcome_count") or summary.get("outcome_count") or 0),
            "regime_count": int(summary.get("regime_count") or len(summary.get("regimes") or [])),
            "net_pnl": _number(summary.get("net_pnl")),
            "drawdown_contribution": max(_number(summary.get("drawdown_contribution")), 0.0),
            "qualified_agent_count": len(qualified),
        }
        checks = {
            "minimum_outcomes": metrics["outcome_count"] >= self.policy.minimum_outcomes,
            "multiple_market_regimes": metrics["regime_count"] >= self.policy.minimum_regimes,
            "positive_attributed_pnl": metrics["net_pnl"] > self.policy.minimum_attributed_pnl,
            "drawdown_within_policy": metrics["drawdown_contribution"] <= self.policy.maximum_drawdown_contribution,
            "qualified_agents_present": bool(qualified),
        }
        return ChallengerEvaluation(
            eligible=all(checks.values()),
            passed_gates=tuple(sorted(key for key, value in checks.items() if value)),
            failed_gates=tuple(sorted(key for key, value in checks.items() if not value)),
            metrics=metrics,
        )

    def create(
        self,
        *,
        scope: str,
        source_experiment_id: str,
        strategy_config_patch: Mapping[str, Any],
        learning_summary: Mapping[str, Any],
        actor: str = "self-learning-supervisor",
        now_ms: int | None = None,
    ) -> dict[str, Any]:
        source = self.experiments.get(source_experiment_id)
        if source is None:
            raise KeyError(source_experiment_id)
        timestamp = _timestamp(now_ms)
        summary = _copy(learning_summary)
        evaluation = self.evaluate_learning_summary(summary)
        patch = _copy(strategy_config_patch)
        config = {**dict(source.get("strategy_config") or {}), **patch}
        identity = {
            "scope": scope,
            "source": source_experiment_id,
            "commit": source.get("commit_sha"),
            "config": config,
            "evidence": _digest(summary),
        }
        challenger_id = "slc_" + _digest(identity)[:32]
        existing = self.database.get_json(_CHALLENGERS, challenger_id)
        if existing is not None:
            return {**dict(existing["value"]), "version": int(existing["version"]), "idempotent": True}
        experiment = self.experiments.create(
            experiment_id=challenger_id,
            commit_sha=str(source.get("commit_sha") or ""),
            manifest=dict(source.get("manifest") or {}),
            strategy_name=str(source.get("strategy_name") or "challenger"),
            strategy_config=config,
            backtest_config=dict(source.get("backtest_config") or {}),
            metadata={
                "origin": "self_learning",
                "scope": scope,
                "source_experiment_id": source_experiment_id,
                "learning_evidence_sha256": identity["evidence"],
            },
            created_at_ms=timestamp,
        )
        experiment = self.experiments.record_result(
            challenger_id,
            "self_learning_evidence",
            {"summary": summary, "evaluation": evaluation.to_dict(), "evidence_sha256": identity["evidence"]},
            actor=actor,
            expected_version=int(experiment["version"]),
            updated_at_ms=timestamp,
        )
        document = {
            "challenger_id": challenger_id,
            "experiment_id": challenger_id,
            "scope": scope,
            "source_experiment_id": source_experiment_id,
            "status": "awaiting_validation" if evaluation.eligible else "blocked",
            "evaluation": evaluation.to_dict(),
            "learning_summary": summary,
            "created_at_ms": timestamp,
            "paper_research_only": True,
            "automatic_execution_promotion": False,
            "runtime_flags_changed": False,
        }
        version = self.database.put_json(_CHALLENGERS, challenger_id, document, expected_version=0)
        self.database.append_event(
            _EVENTS,
            "research_challenger",
            challenger_id,
            {"scope": scope, "eligible": evaluation.eligible},
            created_at_ms=timestamp,
        )
        return {**document, "version": version, "experiment_version": int(experiment["version"]), "idempotent": False}

    def evaluate_experiment(self, challenger_id: str) -> dict[str, Any]:
        current = self.database.get_json(_CHALLENGERS, challenger_id)
        if current is None:
            raise KeyError(challenger_id)
        experiment = self.experiments.get(challenger_id)
        if experiment is None:
            raise RuntimeError("challenger experiment is missing")
        results = experiment.get("results") if isinstance(experiment.get("results"), Mapping) else {}
        walk = results.get("walk_forward") if isinstance(results.get("walk_forward"), Mapping) else {}
        benchmarks = results.get("benchmarks") if isinstance(results.get("benchmarks"), Mapping) else {}
        validation = results.get("data_validation") if isinstance(results.get("data_validation"), Mapping) else {}
        checks = {
            "experiment_completed": str(experiment.get("status") or "") in {"completed", "promotion_pending", "promoted", "rejected"},
            "walk_forward_present": bool(walk),
            "positive_oos_pnl": bool(walk) and _number(walk.get("net_pnl")) > 0,
            "drawdown_finite": bool(walk) and _number(walk.get("max_drawdown_percent")) >= 0,
            "benchmarks_present": bool(benchmarks),
            "data_validation_passed": bool(validation.get("valid", validation.get("status") == "ok")),
            "learning_gates_passed": not bool((current["value"].get("evaluation") or {}).get("failed_gates")),
        }
        return {
            "challenger_id": challenger_id,
            "eligible_for_paper_leadership": all(checks.values()),
            "passed_gates": sorted(key for key, value in checks.items() if value),
            "failed_gates": sorted(key for key, value in checks.items() if not value),
            "metrics": {
                "oos_net_pnl": _number(walk.get("net_pnl")),
                "max_drawdown_percent": _number(walk.get("max_drawdown_percent")),
                "profitable_window_percent": _number(walk.get("profitable_window_percent")),
            },
            "automatic_execution_promotion": False,
        }

    def promote_paper_research_champion(self, challenger_id: str, *, actor: str = "self-learning-supervisor", now_ms: int | None = None) -> dict[str, Any]:
        current = self.database.get_json(_CHALLENGERS, challenger_id)
        if current is None:
            raise KeyError(challenger_id)
        evaluation = self.evaluate_experiment(challenger_id)
        if not evaluation["eligible_for_paper_leadership"]:
            raise ValueError("challenger failed Paper research leadership gates")
        scope = str(current["value"].get("scope") or "")
        previous = self.database.get_json(_LEADERSHIP, scope)
        version = int(previous["version"]) if previous else 0
        previous_value = dict(previous["value"]) if previous else {}
        old_pnl = _number((previous_value.get("metrics") or {}).get("oos_net_pnl"))
        new_pnl = _number(evaluation["metrics"].get("oos_net_pnl"))
        if previous_value.get("champion_experiment_id") and new_pnl < old_pnl * (1 + self.policy.minimum_challenger_improvement):
            raise ValueError("challenger improvement is below Paper research threshold")
        decision = {
            "scope": scope,
            "champion_experiment_id": challenger_id,
            "previous_champion_experiment_id": str(previous_value.get("champion_experiment_id") or ""),
            "challenger_id": challenger_id,
            "metrics": evaluation["metrics"],
            "actor": actor,
            "decided_at_ms": _timestamp(now_ms),
            "paper_research_only": True,
            "manual_execution_promotion_required": True,
            "automatic_execution_promotion": False,
            "runtime_flags_changed": False,
        }
        decision["evidence_sha256"] = _digest(decision)
        new_version = self.database.put_json(_LEADERSHIP, scope, decision, expected_version=version)
        updated = {**dict(current["value"]), "status": "paper_research_champion"}
        self.database.put_json(_CHALLENGERS, challenger_id, updated, expected_version=int(current["version"]))
        return {**decision, "version": new_version}

    def leadership(self, scope: str) -> dict[str, Any]:
        current = self.database.get_json(_LEADERSHIP, scope)
        if current is None:
            return {"scope": scope, "champion_experiment_id": "", "version": 0, "paper_research_only": True, "automatic_execution_promotion": False}
        return {**dict(current["value"]), "version": int(current["version"])}

    def list_challengers(self, *, limit: int = 500) -> list[dict[str, Any]]:
        return [{**dict(row["value"]), "version": int(row["version"])} for row in list_json_items(self.database, _CHALLENGERS, limit=limit, newest_first=True)]


def _number(value: Any) -> float:
    parsed = float(value or 0.0)
    if not math.isfinite(parsed):
        raise ValueError("numeric evidence must be finite")
    return parsed


def _timestamp(value: int | None) -> int:
    return int(time.time() * 1000) if value is None else int(value)


def _copy(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False))


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


__all__ = ["ChallengerEvaluation", "ResearchChallengerService"]
