"""Paper-versus-Testnet shadow execution gate.

The gate combines fill divergence evidence with execution identity state. It is
read-only with respect to exchange execution and can never promote a strategy
or enable Mainnet automatically.
"""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import asdict, dataclass
from typing import Any, Iterable, Mapping

from storage import ProjectDatabase

from exchange_connector.execution_idempotency import ExecutionIdempotencyRepository
from exchange_connector.execution_kill_switch import PersistentExecutionKillSwitch
from .fill_divergence import (
    DivergenceThresholds,
    FillDivergenceAnalyzer,
    FillObservation,
    FillValidationRepository,
)


@dataclass(frozen=True, slots=True)
class ShadowExecutionReport:
    report_id: str
    experiment_id: str
    fill_report_id: str
    matched_count: int
    unresolved_execution_count: int
    kill_switch_active: bool
    restart_safe: bool
    shadow_eligible: bool
    controlled_live_eligible: bool
    failed_gates: tuple[str, ...]
    evidence_sha256: str
    created_at_ms: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ShadowExecutionValidator:
    """Validate Paper/Testnet equivalence and execution-state integrity."""

    def __init__(
        self,
        *,
        database: ProjectDatabase | None = None,
        thresholds: DivergenceThresholds | None = None,
    ) -> None:
        self.database = database or ProjectDatabase()
        self.database.initialize()
        self.analyzer = FillDivergenceAnalyzer(thresholds)
        self.reports = FillValidationRepository(self.database)
        self.idempotency = ExecutionIdempotencyRepository(
            database=self.database,
            environment="testnet",
        )
        self.kill_switch = PersistentExecutionKillSwitch(self.database)

    def validate(
        self,
        paper_fills: Iterable[FillObservation | Mapping[str, Any]],
        testnet_fills: Iterable[FillObservation | Mapping[str, Any]],
        *,
        experiment_id: str,
        actor: str,
        report_id: str | None = None,
        created_at_ms: int | None = None,
    ) -> ShadowExecutionReport:
        timestamp = int(created_at_ms or time.time() * 1000)
        clean_experiment = _identifier(experiment_id, "experiment_id")
        clean_actor = _identifier(actor, "actor")
        fill_report = self.analyzer.analyze(
            paper_fills,
            testnet_fills,
            report_id=f"{report_id or 'shadow'}_fills",
            created_at_ms=timestamp,
        )
        self.reports.save(
            fill_report,
            experiment_id=clean_experiment,
            actor=clean_actor,
        )

        identity = self.idempotency.snapshot()
        unresolved_count = len(identity.get("unresolved", []))
        restart_safe = bool(identity.get("restart_safe")) and unresolved_count == 0
        switch = self.kill_switch.state()
        failed = list(fill_report.failed_gates)
        if unresolved_count:
            failed.append("unresolved_execution_state")
        if not restart_safe:
            failed.append("execution_restart_not_safe")
        if switch.active:
            failed.append("execution_kill_switch_active")

        payload = {
            "experiment_id": clean_experiment,
            "fill_report": fill_report.to_dict(),
            "unresolved_execution_count": unresolved_count,
            "restart_safe": restart_safe,
            "kill_switch": switch.to_dict(),
            "failed_gates": sorted(set(failed)),
            "created_at_ms": timestamp,
        }
        digest = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        identifier = _identifier(
            report_id or f"shadow_{clean_experiment}_{timestamp}",
            "report_id",
        )
        report = ShadowExecutionReport(
            report_id=identifier,
            experiment_id=clean_experiment,
            fill_report_id=fill_report.report_id,
            matched_count=fill_report.matched_count,
            unresolved_execution_count=unresolved_count,
            kill_switch_active=switch.active,
            restart_safe=restart_safe,
            shadow_eligible=not failed,
            controlled_live_eligible=False,
            failed_gates=tuple(sorted(set(failed))),
            evidence_sha256=digest,
            created_at_ms=timestamp,
        )
        self.database.put_json(
            "shadow_execution_reports_v1",
            identifier,
            report.to_dict(),
            expected_version=0,
        )
        self.database.append_event(
            "shadow_execution_report_events_v1",
            "shadow_validation",
            identifier,
            {
                "experiment_id": clean_experiment,
                "actor": clean_actor,
                "shadow_eligible": report.shadow_eligible,
                "controlled_live_eligible": False,
                "evidence_sha256": digest,
            },
            created_at_ms=timestamp,
        )
        return report


def _identifier(value: Any, name: str) -> str:
    clean = str(value).strip()
    if not clean or len(clean) > 160:
        raise ValueError(f"{name} is required and must be <=160 characters")
    return clean


__all__ = ["ShadowExecutionReport", "ShadowExecutionValidator"]
