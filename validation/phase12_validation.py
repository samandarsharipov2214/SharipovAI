"""Canonical Phase 12 expected/Paper/Testnet validation orchestration."""
from __future__ import annotations

import hashlib
import json
import time
from typing import Any, Iterable, Mapping

from experiments import ExperimentRegistry
from storage import ProjectDatabase

from .fill_divergence import FillDivergenceAnalyzer, FillValidationRepository
from .paper_fill_validation import ExpectedPaperFillAnalyzer

_NAMESPACE = "phase12_fill_validation"
_EVENT_NAMESPACE = "phase12_fill_validation_events"


class Phase12FillValidationService:
    def __init__(
        self,
        database: ProjectDatabase | None = None,
        *,
        experiments: ExperimentRegistry | None = None,
        expected_analyzer: ExpectedPaperFillAnalyzer | None = None,
        shadow_analyzer: FillDivergenceAnalyzer | None = None,
    ) -> None:
        self.database = database or ProjectDatabase()
        self.database.initialize()
        self.experiments = experiments or ExperimentRegistry(self.database)
        self.expected_analyzer = expected_analyzer or ExpectedPaperFillAnalyzer()
        self.shadow_analyzer = shadow_analyzer or FillDivergenceAnalyzer()
        self.shadow_repository = FillValidationRepository(self.database)

    def validate(
        self,
        *,
        experiment_id: str,
        expected_paper_fills: Iterable[Mapping[str, Any]],
        actual_paper_fills: Iterable[Mapping[str, Any]],
        testnet_fills: Iterable[Mapping[str, Any]],
        actor: str,
        now_ms: int | None = None,
    ) -> dict[str, Any]:
        experiment = self.experiments.get(experiment_id)
        if experiment is None:
            raise KeyError(experiment_id)
        clean_actor = str(actor or "").strip()
        if not clean_actor or len(clean_actor) > 200:
            raise ValueError("invalid actor")
        timestamp = int(time.time() * 1000) if now_ms is None else int(now_ms)
        if timestamp <= 0:
            raise ValueError("now_ms must be positive")
        expected_rows = list(expected_paper_fills)
        paper_rows = list(actual_paper_fills)
        testnet_rows = list(testnet_fills)
        input_sha = _digest({
            "experiment_id": experiment_id,
            "expected_paper_fills": expected_rows,
            "actual_paper_fills": paper_rows,
            "testnet_fills": testnet_rows,
        })
        expected_report = self.expected_analyzer.analyze(
            expected_rows,
            paper_rows,
            report_id=f"paperfill_{input_sha[:24]}",
            created_at_ms=timestamp,
        )
        shadow_report = self.shadow_analyzer.analyze(
            paper_rows,
            testnet_rows,
            report_id=f"fillval_{input_sha[24:48]}",
            created_at_ms=timestamp,
        )
        document = {
            "experiment_id": experiment_id,
            "input_sha256": input_sha,
            "expected_vs_actual_paper": expected_report.to_dict(),
            "paper_vs_testnet_shadow": shadow_report.to_dict(),
            "promotion_eligible": bool(expected_report.validation_passed and shadow_report.promotion_eligible),
            "failed_gates": sorted(set([*expected_report.failed_gates, *shadow_report.failed_gates])),
            "created_at_ms": timestamp,
            "actor": clean_actor,
            "automatic_promotion": False,
            "manual_decision_required": True,
            "runtime_flags_changed": False,
        }
        document["evidence_sha256"] = _digest(_stable_evidence(document))
        report_id = "phase12fill_" + document["evidence_sha256"][:32]
        existing = self.database.get_json(_NAMESPACE, report_id)
        if existing is not None:
            stored = dict(existing["value"])
            self._attach_experiment_result(
                experiment_id,
                report_id=report_id,
                document=stored,
                stored_shadow=self.shadow_repository.get(shadow_report.report_id) or shadow_report.to_dict(),
                actor=clean_actor,
                timestamp=timestamp,
            )
            return {"report_id": report_id, **stored, "version": int(existing["version"]), "idempotent": True}
        stored_shadow = self.shadow_repository.get(shadow_report.report_id)
        if stored_shadow is None:
            stored_shadow = self.shadow_repository.save(shadow_report, experiment_id=experiment_id, actor=clean_actor)
        version = self.database.put_json(_NAMESPACE, report_id, document, expected_version=0)
        event_id = self.database.append_event(
            _EVENT_NAMESPACE,
            "fill_validation",
            report_id,
            {
                "experiment_id": experiment_id,
                "promotion_eligible": document["promotion_eligible"],
                "failed_gates": document["failed_gates"],
                "evidence_sha256": document["evidence_sha256"],
            },
            event_id=f"phase12-fill-validation-{report_id}",
            created_at_ms=timestamp,
        )
        self._attach_experiment_result(
            experiment_id,
            report_id=report_id,
            document=document,
            stored_shadow=stored_shadow,
            actor=clean_actor,
            timestamp=timestamp,
        )
        return {"report_id": report_id, **document, "version": version, "event_id": event_id, "idempotent": False}

    def _attach_experiment_result(
        self,
        experiment_id: str,
        *,
        report_id: str,
        document: Mapping[str, Any],
        stored_shadow: Mapping[str, Any],
        actor: str,
        timestamp: int,
    ) -> None:
        current = self.experiments.get(experiment_id)
        if current is None:
            raise RuntimeError("experiment disappeared during validation")
        results = current.get("results") if isinstance(current.get("results"), Mapping) else {}
        existing = results.get("phase12_fill_validation")
        if isinstance(existing, Mapping):
            if str(existing.get("evidence_sha256") or "") != str(document.get("evidence_sha256") or ""):
                raise ValueError("experiment already contains conflicting Phase 12 validation")
            return
        self.experiments.record_result(
            experiment_id,
            "phase12_fill_validation",
            {
                "report_id": report_id,
                "evidence_sha256": document["evidence_sha256"],
                "promotion_eligible": document["promotion_eligible"],
                "failed_gates": document["failed_gates"],
                "expected_vs_actual_paper": document["expected_vs_actual_paper"],
                "paper_vs_testnet_shadow": dict(stored_shadow),
                "automatic_promotion": False,
                "manual_decision_required": True,
            },
            actor=actor,
            expected_version=int(current["version"]),
            updated_at_ms=timestamp,
        )


def _stable_evidence(value: Any) -> Any:
    volatile = {"created_at_ms", "updated_at_ms", "database_updated_at_ms", "event_id", "version", "actor"}
    if isinstance(value, Mapping):
        return {str(key): _stable_evidence(item) for key, item in value.items() if str(key) not in volatile and str(key) != "evidence_sha256"}
    if isinstance(value, list):
        return [_stable_evidence(item) for item in value]
    if isinstance(value, tuple):
        return [_stable_evidence(item) for item in value]
    return value


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


__all__ = ["Phase12FillValidationService"]
