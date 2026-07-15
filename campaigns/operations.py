"""Operational read model and gated launcher for the first bounded Testnet campaign.

This service does not mutate environment variables, enable Mainnet, disable the
kill switch or approve an experiment.  It may start a campaign only after every
existing manual, CI, credential, private-stream and reconciliation gate is green.
"""
from __future__ import annotations

import os
import time
from dataclasses import asdict, dataclass
from typing import Any, Mapping

from experiments.registry import ExperimentRegistry
from storage import ProjectDatabase

from .core import FinalPromotionReportEngine, TestnetShadowCampaign
from .orchestrator import ScheduledCampaignOrchestrator

FIRST_TESTNET_CONFIRMATION = "I_APPROVE_BOUNDED_TESTNET_SHADOW_CAMPAIGN"
_RELEASE_GATE_VALUE = "green"
_TERMINAL = {"completed", "blocked", "cancelled"}
_TRUE = {"1", "true", "yes", "on"}


@dataclass(frozen=True, slots=True)
class FirstTestnetCampaignPlan:
    environment: str = "testnet"
    category: str = "spot"
    minimum_notional_usdt: float = 10.0
    maximum_notional_usdt: float = 25.0
    minimum_matched_fills: int = 20
    maximum_orphan_executions: int = 0
    maximum_duplicate_orders: int = 0
    maximum_unresolved_orders: int = 0
    automatic_final_report: bool = True
    mainnet_enabled: bool = False
    changes_runtime_flags: bool = False
    confirmation_phrase: str = FIRST_TESTNET_CONFIRMATION


class CampaignOperationsService:
    """Build the campaign control-plane read model and enforce launch gates."""

    def __init__(
        self,
        database: ProjectDatabase | None = None,
        *,
        orchestrator: ScheduledCampaignOrchestrator | None = None,
        campaign: TestnetShadowCampaign | None = None,
        reports: FinalPromotionReportEngine | None = None,
    ) -> None:
        self.database = database or ProjectDatabase()
        self.database.initialize()
        self.campaign = campaign or TestnetShadowCampaign(self.database)
        self.orchestrator = orchestrator or ScheduledCampaignOrchestrator(
            self.database,
            campaign=self.campaign,
        )
        self.reports = reports or FinalPromotionReportEngine(self.database)
        self.registry = ExperimentRegistry(self.database)
        self.plan_contract = FirstTestnetCampaignPlan(
            minimum_notional_usdt=self.campaign.policy.minimum_testnet_notional_usdt,
            maximum_notional_usdt=self.campaign.policy.maximum_testnet_notional_usdt,
            minimum_matched_fills=self.campaign.policy.minimum_matched_fills,
            maximum_orphan_executions=self.campaign.policy.maximum_orphan_orders,
            maximum_duplicate_orders=self.campaign.policy.maximum_duplicate_orders,
            maximum_unresolved_orders=self.campaign.policy.maximum_unresolved_orders,
        )

    def snapshot(self) -> dict[str, Any]:
        schedules = self.orchestrator.list_schedules(limit=500)
        campaigns = self.campaign.list(limit=500)
        reports = self.reports.list(limit=500)
        active_rows = [row for row in campaigns if str(row.get("status")) not in _TERMINAL]
        active = active_rows[0] if len(active_rows) == 1 else None
        latest = campaigns[0] if campaigns else None
        selected = active or latest
        return {
            "status": "ok" if len(active_rows) <= 1 else "blocked",
            "checked_at_ms": int(time.time() * 1000),
            "orchestrator": self.orchestrator.status(),
            "plan": self.first_testnet_plan(),
            "schedule_count": len(schedules),
            "schedules": schedules,
            "campaign_count": len(campaigns),
            "active_campaign_count": len(active_rows),
            "active_campaign": self._campaign_view(active) if active else {},
            "latest_campaign": self._campaign_view(selected) if selected else {},
            "recent_campaigns": [self._campaign_view(row) for row in campaigns[:20]],
            "report_count": len(reports),
            "recent_reports": reports[:20],
            "single_global_campaign_authorization": len(active_rows) <= 1,
            "mainnet_enabled": False,
            "runtime_flags_changed": False,
        }

    def first_testnet_plan(
        self,
        *,
        experiment_id: str = "",
        confirmation: str = "",
    ) -> dict[str, Any]:
        execution = self._execution_status()
        private_stream = self._private_stream_status()
        campaigns = self.campaign.list(limit=2_000)
        non_terminal = [row for row in campaigns if str(row.get("status")) not in _TERMINAL]
        experiment_gate = self._experiment_gate(experiment_id) if experiment_id else {
            "passed": False,
            "reason": "experiment_id_required",
        }
        gates = {
            "release_gate_green": os.getenv("PHASE6_TESTNET_RELEASE_GATE", "").strip().lower()
            == _RELEASE_GATE_VALUE,
            "sandbox_mode": str(execution.get("mode", "")).lower() == "sandbox",
            "testnet_credentials_configured": bool(execution.get("credentials_configured")),
            "testnet_execution_enabled": bool(execution.get("testnet_execution_enabled")),
            "execution_kill_switch_off": not bool(execution.get("kill_switch", True)),
            "mainnet_compiled_out": execution.get("mainnet_execution_compiled") is False,
            "mainnet_hard_blocked": bool(execution.get("mainnet_hard_blocked", True)),
            "testnet_bridge_enabled": _truthy("AUTONOMOUS_TESTNET_BRIDGE_ENABLED")
            and _truthy("AUTONOMOUS_TESTNET_ENABLED"),
            "private_order_execution_stream_enabled": _truthy("FEATURE_BYBIT_PRIVATE_ORDER_WS"),
            "runtime_fill_harvester_enabled": _truthy("RUNTIME_FILL_HARVESTER_ENABLED"),
            "scheduled_orchestrator_enabled": _truthy("SCHEDULED_CAMPAIGN_ORCHESTRATOR_ENABLED"),
            "private_stream_ready": bool(private_stream.get("ready")),
            "execution_restart_safe": bool(execution.get("restart_safe")),
            "no_active_campaign": not non_terminal,
            "approved_promoted_experiment": bool(experiment_gate.get("passed")),
            "exact_manual_confirmation": confirmation == FIRST_TESTNET_CONFIRMATION,
        }
        blockers = [name for name, passed in gates.items() if not passed]
        return {
            "status": "ready" if not blockers else "blocked",
            "can_start": not blockers,
            "contract": asdict(self.plan_contract),
            "gates": gates,
            "blockers": blockers,
            "experiment": experiment_gate,
            "execution": execution,
            "private_stream": private_stream,
            "non_terminal_campaign_ids": [str(row.get("campaign_id", "")) for row in non_terminal],
            "runtime_flags_changed": False,
            "mainnet_enabled": False,
        }

    def start_first_testnet_campaign(
        self,
        *,
        experiment_id: str,
        scope: str,
        actor: str,
        confirmation: str,
        now_ms: int | None = None,
    ) -> dict[str, Any]:
        readiness = self.first_testnet_plan(
            experiment_id=experiment_id,
            confirmation=confirmation,
        )
        if not readiness["can_start"]:
            raise RuntimeError(
                "first Testnet campaign is blocked: " + ", ".join(readiness["blockers"])
            )
        timestamp = int(time.time() * 1000) if now_ms is None else int(now_ms)
        campaign = self.campaign.start(
            experiment_id=experiment_id,
            scope=scope,
            actor=actor,
            schedule_id="phase6-first-testnet",
            now_ms=timestamp,
        )
        cycle = self.campaign.run_cycle(
            str(campaign["campaign_id"]),
            actor=actor,
            now_ms=timestamp,
        )
        return {
            "status": "started",
            "campaign": self._campaign_view(cycle),
            "automatic_final_report": True,
            "manual_promotion_required": True,
            "runtime_flags_changed": False,
            "mainnet_enabled": False,
        }

    def _campaign_view(self, row: Mapping[str, Any] | None) -> dict[str, Any]:
        if not row:
            return {}
        campaign = dict(row)
        metrics = campaign.get("metrics") if isinstance(campaign.get("metrics"), Mapping) else {}
        matched = int(metrics.get("matched_fill_count", 0) or 0)
        target = int(
            (campaign.get("policy") or {}).get("minimum_matched_fills", 20)
            if isinstance(campaign.get("policy"), Mapping)
            else 20
        )
        final_report_id = str(campaign.get("final_report_id") or "")
        report = self.reports.get(final_report_id) if final_report_id else None
        actual_fee_total = self._actual_fee_total(campaign)
        zero_identity_errors = (
            int(metrics.get("orphan_execution_count", 0) or 0) == 0
            and int(metrics.get("duplicate_order_count", 0) or 0) == 0
            and int(metrics.get("unresolved_order_count", 0) or 0) == 0
        )
        report_ready = bool(
            campaign.get("status") == "completed"
            and matched >= target
            and zero_identity_errors
            and metrics.get("actual_execution_fees")
        )
        return {
            **campaign,
            "progress": {
                "matched_fills": matched,
                "target_fills": target,
                "percent": round(min(100.0, matched / max(target, 1) * 100.0), 2),
                "remaining_fills": max(target - matched, 0),
            },
            "identity_integrity": {
                "orphan_execution_count": int(metrics.get("orphan_execution_count", 0) or 0),
                "duplicate_order_count": int(metrics.get("duplicate_order_count", 0) or 0),
                "unresolved_order_count": int(metrics.get("unresolved_order_count", 0) or 0),
                "zero_identity_errors": zero_identity_errors,
            },
            "fees": {
                "actual_execution_fees": bool(metrics.get("actual_execution_fees")),
                "actual_fee_total": actual_fee_total,
                "currency": "USDT-equivalent",
            },
            "final_report": {
                "ready": report_ready,
                "generated": bool(report),
                "report_id": final_report_id,
                "status": str((report or {}).get("status", "pending")),
                "manual_decision_required": bool(
                    (report or {}).get("manual_decision_required", True)
                ),
            },
        }

    def _actual_fee_total(self, campaign: Mapping[str, Any]) -> float:
        campaign_id = str(campaign.get("campaign_id") or "")
        links = {
            str(item.get("order_link_id") or "")
            for item in self.campaign._campaign_records(campaign_id)
            if item.get("order_link_id")
        }
        snapshot = self.campaign.executions.snapshot()
        total = 0.0
        for item in snapshot.get("managed_orders", []):
            if not isinstance(item, Mapping):
                continue
            if links and str(item.get("order_link_id") or "") not in links:
                continue
            try:
                total += float(item.get("actual_fee") or 0.0)
            except (TypeError, ValueError):
                continue
        return round(total, 12)

    def _execution_status(self) -> dict[str, Any]:
        client = getattr(getattr(self.campaign, "bridge", None), "client", None)
        status = client.status() if client is not None and callable(getattr(client, "status", None)) else {}
        return dict(status) if isinstance(status, Mapping) else {}

    def _private_stream_status(self) -> dict[str, Any]:
        try:
            return self.campaign.private_stream.evaluate(
                required=True,
                now_ms=int(time.time() * 1000),
            ).to_dict()
        except Exception as exc:
            return {
                "ready": False,
                "status": "unavailable",
                "error": f"{type(exc).__name__}: {exc}",
            }

    def _experiment_gate(self, experiment_id: str) -> dict[str, Any]:
        clean = str(experiment_id or "").strip()
        if not clean:
            return {"passed": False, "reason": "experiment_id_required"}
        experiment = self.registry.get(clean)
        if experiment is None:
            return {"passed": False, "reason": "experiment_not_found", "experiment_id": clean}
        promotion = experiment.get("promotion")
        report = promotion.get("report") if isinstance(promotion, Mapping) else None
        manual = promotion.get("manual_decision") if isinstance(promotion, Mapping) else None
        passed = bool(
            str(experiment.get("status")) == "promoted"
            and isinstance(promotion, Mapping)
            and str(promotion.get("status")) == "approved"
            and str(promotion.get("target_stage")) == "testnet"
            and isinstance(report, Mapping)
            and bool(report.get("automated_gate_passed"))
            and not report.get("failed_gates")
            and isinstance(manual, Mapping)
            and bool(manual.get("approved"))
        )
        return {
            "passed": passed,
            "reason": "approved" if passed else "manual_or_automated_testnet_approval_missing",
            "experiment_id": clean,
            "status": experiment.get("status"),
            "promotion_status": promotion.get("status") if isinstance(promotion, Mapping) else "",
            "target_stage": promotion.get("target_stage") if isinstance(promotion, Mapping) else "",
        }


def _truthy(name: str) -> bool:
    return os.getenv(name, "0").strip().lower() in _TRUE


__all__ = [
    "CampaignOperationsService",
    "FIRST_TESTNET_CONFIRMATION",
    "FirstTestnetCampaignPlan",
]
