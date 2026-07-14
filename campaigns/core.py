"""Scheduled, evidence-gated Testnet shadow campaign orchestration."""
from __future__ import annotations

import hashlib
import json
import math
import os
import threading
import time
from dataclasses import asdict, dataclass
from typing import Any, Mapping

from autonomous_trading.shadow_bridge import ShadowModeTestnetBridge
from autonomous_trading.startup_reconciliation import StartupExecutionReconciler
from exchange_connector.bybit_execution_state import BybitExecutionStateStore
from exchange_connector.bybit_order_state import BybitOrderStateStore
from exchange_connector.private_ws_gate import PrivateStreamHealthRepository
from experiments.champion_challenger import ChampionChallengerRegistry
from experiments.promotion import PromotionGateEngine, PromotionTarget
from experiments.registry import ExperimentRegistry
from storage import ProjectDatabase, list_json_items
from validation.fill_divergence import FillValidationRepository
from validation.runtime_fill_harvester import RuntimeFillHarvester

_SCHEDULE_NAMESPACE = "scheduled_campaign_schedules"
_CAMPAIGN_NAMESPACE = "testnet_shadow_campaigns"
_ACTIVE_NAMESPACE = "scheduled_campaign_active"
_REPORT_NAMESPACE = "final_promotion_reports"
_EVENT_NAMESPACE = "scheduled_campaign_events"
_TERMINAL_CAMPAIGNS = {"completed", "blocked", "cancelled"}
_TRUE = {"1", "true", "yes", "on"}


@dataclass(frozen=True, slots=True)
class ShadowCampaignPolicy:
    minimum_testnet_notional_usdt: float = 10.0
    maximum_testnet_notional_usdt: float = 25.0
    minimum_matched_fills: int = 20
    maximum_unmatched_fills: int = 0
    maximum_orphan_orders: int = 0
    maximum_duplicate_orders: int = 0
    maximum_unresolved_orders: int = 0
    authorization_ttl_seconds: int = 3_600

    def __post_init__(self) -> None:
        if not 10.0 <= self.minimum_testnet_notional_usdt <= 25.0:
            raise ValueError("campaign minimum notional must be within 10..25 USDT")
        if not self.minimum_testnet_notional_usdt <= self.maximum_testnet_notional_usdt <= 25.0:
            raise ValueError("campaign maximum notional must be within minimum..25 USDT")
        if self.minimum_matched_fills < 20:
            raise ValueError("campaign requires at least 20 matched fills")


class TestnetShadowCampaign:
    """Run one bounded campaign without changing runtime execution authority."""

    def __init__(
        self,
        database: ProjectDatabase | None = None,
        *,
        bridge: ShadowModeTestnetBridge | None = None,
        harvester: RuntimeFillHarvester | None = None,
        orders: BybitOrderStateStore | None = None,
        executions: BybitExecutionStateStore | None = None,
        policy: ShadowCampaignPolicy | None = None,
    ) -> None:
        self.database = database or ProjectDatabase()
        self.database.initialize()
        self.policy = policy or ShadowCampaignPolicy()
        self.orders = orders or BybitOrderStateStore(database=self.database, environment="testnet")
        self.executions = executions or BybitExecutionStateStore(database=self.database, environment="testnet")
        self.bridge = bridge or ShadowModeTestnetBridge(database=self.database)
        self.harvester = harvester or RuntimeFillHarvester(
            database=self.database,
            private_orders=self.orders,
            private_executions=self.executions,
        )
        self.registry = ExperimentRegistry(self.database)
        self.private_stream = PrivateStreamHealthRepository(
            database=self.database,
            environment="testnet",
        )

    def start(
        self,
        *,
        experiment_id: str,
        scope: str,
        actor: str,
        schedule_id: str = "",
        campaign_id: str | None = None,
        now_ms: int | None = None,
    ) -> dict[str, Any]:
        experiment = _approved_testnet_experiment(self.registry, experiment_id)
        timestamp = _timestamp(now_ms)
        clean_scope = _identifier(scope, "scope")
        clean_schedule = _optional_identifier(schedule_id, "schedule_id")
        identifier = _identifier(
            campaign_id
            or "campaign_"
            + _digest(
                {
                    "experiment_id": experiment["experiment_id"],
                    "scope": clean_scope,
                    "schedule_id": clean_schedule,
                    "started_at_ms": timestamp,
                }
            )[:32],
            "campaign_id",
        )
        payload = {
            "campaign_id": identifier,
            "experiment_id": experiment["experiment_id"],
            "scope": clean_scope,
            "schedule_id": clean_schedule,
            "status": "scheduled",
            "policy": asdict(self.policy),
            "started_at_ms": timestamp,
            "updated_at_ms": timestamp,
            "completed_at_ms": 0,
            "cycle_count": 0,
            "metrics": {},
            "failed_gates": [],
            "last_evidence": {},
            "final_report_id": "",
            "actor": _identifier(actor, "actor"),
            "runtime_flags_changed": False,
            "mainnet_enabled": False,
        }
        self.database.put_json(_CAMPAIGN_NAMESPACE, identifier, payload, expected_version=0)
        self._activate(payload, now_ms=timestamp)
        self._event(identifier, "campaign_started", payload, timestamp)
        return {**payload, "version": 1}

    def get(self, campaign_id: str) -> dict[str, Any] | None:
        current = self.database.get_json(_CAMPAIGN_NAMESPACE, _identifier(campaign_id, "campaign_id"))
        if current is None:
            return None
        return {**dict(current["value"]), "version": int(current["version"])}

    def list(self, *, limit: int = 200) -> list[dict[str, Any]]:
        return [
            {**dict(item["value"]), "version": int(item["version"])}
            for item in list_json_items(
                self.database,
                _CAMPAIGN_NAMESPACE,
                limit=min(max(int(limit), 1), 2_000),
                newest_first=True,
            )
        ]

    def run_cycle(self, campaign_id: str, *, actor: str = "campaign-orchestrator", now_ms: int | None = None) -> dict[str, Any]:
        campaign = self.get(campaign_id)
        if campaign is None:
            raise KeyError(campaign_id)
        if campaign["status"] in _TERMINAL_CAMPAIGNS:
            return campaign
        _approved_testnet_experiment(self.registry, campaign["experiment_id"])
        timestamp = _timestamp(now_ms)
        self._activate(campaign, now_ms=timestamp)
        self.bridge.tick()
        validation = self.harvester.harvest(
            experiment_id=campaign["experiment_id"],
            campaign_id=campaign["campaign_id"],
            actor=actor,
            now_ms=timestamp,
        )
        order_snapshot = self.orders.snapshot()
        execution_snapshot = self.executions.snapshot()
        execution_reconciliation = self.executions.reconcile(order_snapshot)
        startup = StartupExecutionReconciler(
            database=self.database,
            environment="testnet",
            require_private_stream=True,
        ).reconcile().to_dict()
        private_stream = self.private_stream.evaluate(required=True, now_ms=timestamp).to_dict()
        records = self._campaign_records(campaign["campaign_id"])
        links = [str(item.get("order_link_id") or "") for item in records if item.get("order_link_id")]
        duplicate_orders = len(links) - len(set(links))
        unresolved = sum(str(item.get("status")) == "unresolved" for item in records)
        invalid_notionals = [
            float(item.get("testnet_notional") or 0.0)
            for item in records
            if str(item.get("status")) == "accepted"
            and not self.policy.minimum_testnet_notional_usdt
            <= float(item.get("testnet_notional") or 0.0)
            <= self.policy.maximum_testnet_notional_usdt
        ]
        campaign_links = set(links)
        orphan_execution_links = [
            link
            for link in execution_reconciliation.get("orphan_execution_links", [])
            if link in campaign_links
        ]
        failed: list[str] = []
        hard_block = False
        if duplicate_orders > self.policy.maximum_duplicate_orders:
            failed.append("duplicate_order_identity")
            hard_block = True
        if len(orphan_execution_links) > self.policy.maximum_orphan_orders:
            failed.append("orphan_execution")
            hard_block = True
        if unresolved > self.policy.maximum_unresolved_orders:
            failed.append("unresolved_order")
            hard_block = True
        if invalid_notionals:
            failed.append("campaign_notional_outside_10_25_usdt")
            hard_block = True
        if execution_snapshot.get("conflicting_duplicate_count", 0):
            failed.append("conflicting_execution_duplicate")
            hard_block = True
        matched = int(validation.get("matched_count", 0) or 0)
        unmatched_paper = int(validation.get("unmatched_paper_count", 0) or 0)
        unmatched_testnet = int(validation.get("unmatched_testnet_count", 0) or 0)
        complete = bool(
            matched >= self.policy.minimum_matched_fills
            and unmatched_paper <= self.policy.maximum_unmatched_fills
            and unmatched_testnet <= self.policy.maximum_unmatched_fills
            and not failed
            and bool(validation.get("promotion_eligible"))
            and bool(startup.get("restart_safe"))
            and bool(private_stream.get("ready"))
            and bool(execution_reconciliation.get("restart_safe"))
            and bool(validation.get("actual_execution_fees"))
        )
        if matched < self.policy.minimum_matched_fills:
            failed.append("minimum_20_matched_fills_pending")
        if unmatched_paper or unmatched_testnet:
            failed.append("unmatched_fill_evidence")
        if not startup.get("restart_safe"):
            failed.append("startup_reconciliation_blocked")
        if not private_stream.get("ready"):
            failed.append("private_stream_not_ready")
        if not execution_reconciliation.get("restart_safe"):
            failed.append("execution_reconciliation_blocked")
        status = "completed" if complete else "blocked" if hard_block else "running"
        metrics = {
            "matched_fill_count": matched,
            "unmatched_paper_count": unmatched_paper,
            "unmatched_testnet_count": unmatched_testnet,
            "accepted_shadow_order_count": sum(str(item.get("status")) == "accepted" for item in records),
            "duplicate_order_count": duplicate_orders,
            "orphan_execution_count": len(orphan_execution_links),
            "unresolved_order_count": unresolved,
            "actual_execution_count": int(execution_snapshot.get("managed_execution_count", 0)),
            "minimum_notional_usdt": self.policy.minimum_testnet_notional_usdt,
            "maximum_notional_usdt": self.policy.maximum_testnet_notional_usdt,
            "actual_execution_fees": bool(validation.get("actual_execution_fees")),
        }
        updated = {
            **{key: value for key, value in campaign.items() if key != "version"},
            "status": status,
            "updated_at_ms": timestamp,
            "completed_at_ms": timestamp if complete else 0,
            "cycle_count": int(campaign.get("cycle_count", 0)) + 1,
            "metrics": metrics,
            "failed_gates": sorted(set(failed)),
            "last_evidence": {
                "fill_validation": validation,
                "startup_reconciliation": startup,
                "private_stream": private_stream,
                "execution_reconciliation": execution_reconciliation,
            },
            "runtime_flags_changed": False,
            "mainnet_enabled": False,
        }
        version = self.database.put_json(
            _CAMPAIGN_NAMESPACE,
            campaign["campaign_id"],
            updated,
            expected_version=int(campaign["version"]),
        )
        result = {**updated, "version": version}
        self._event(campaign["campaign_id"], f"campaign_{status}", metrics, timestamp)
        if status in _TERMINAL_CAMPAIGNS:
            self._deactivate(campaign["campaign_id"], now_ms=timestamp)
        if status == "completed":
            report = FinalPromotionReportEngine(self.database).generate(
                campaign["campaign_id"],
                actor=actor,
                now_ms=timestamp,
            )
            current = self.get(campaign["campaign_id"])
            if current is not None:
                payload = {**{k: v for k, v in current.items() if k != "version"}, "final_report_id": report["report_id"]}
                new_version = self.database.put_json(
                    _CAMPAIGN_NAMESPACE,
                    campaign["campaign_id"],
                    payload,
                    expected_version=int(current["version"]),
                )
                result = {**payload, "version": new_version}
        return result

    def _campaign_records(self, campaign_id: str) -> list[dict[str, Any]]:
        namespace = self.bridge.record_namespace
        return [
            dict(item["value"])
            for item in list_json_items(self.database, namespace)
            if isinstance(item.get("value"), Mapping)
            and str(item["value"].get("campaign_id") or "") == campaign_id
        ]

    def _activate(self, campaign: Mapping[str, Any], *, now_ms: int) -> None:
        payload = {
            "status": "active",
            "campaign_id": campaign["campaign_id"],
            "experiment_id": campaign["experiment_id"],
            "scope": campaign["scope"],
            "minimum_notional_usdt": self.policy.minimum_testnet_notional_usdt,
            "maximum_notional_usdt": self.policy.maximum_testnet_notional_usdt,
            "activated_at_ms": now_ms,
            "expires_at_ms": now_ms + self.policy.authorization_ttl_seconds * 1000,
            "execution_authority": False,
            "mainnet_enabled": False,
        }
        current = self.database.get_json(_ACTIVE_NAMESPACE, "current")
        version = int(current["version"]) if current else 0
        self.database.put_json(_ACTIVE_NAMESPACE, "current", payload, expected_version=version)

    def _deactivate(self, campaign_id: str, *, now_ms: int) -> None:
        current = self.database.get_json(_ACTIVE_NAMESPACE, "current")
        if current is None or str(current["value"].get("campaign_id")) != campaign_id:
            return
        payload = {**dict(current["value"]), "status": "closed", "closed_at_ms": now_ms}
        self.database.put_json(
            _ACTIVE_NAMESPACE,
            "current",
            payload,
            expected_version=int(current["version"]),
        )

    def _event(self, campaign_id: str, action: str, payload: Mapping[str, Any], timestamp: int) -> None:
        self.database.append_event(
            _EVENT_NAMESPACE,
            "testnet_shadow_campaign",
            campaign_id,
            {"action": action, **dict(payload)},
            created_at_ms=timestamp,
        )


class ScheduledCampaignOrchestrator:
    """Schedule approved Testnet experiments without bypassing runtime gates."""

    def __init__(
        self,
        database: ProjectDatabase | None = None,
        *,
        campaign: TestnetShadowCampaign | None = None,
    ) -> None:
        self.database = database or ProjectDatabase()
        self.database.initialize()
        self.registry = ExperimentRegistry(self.database)
        self.campaign = campaign or TestnetShadowCampaign(self.database)
        self.interval = min(max(_finite_env("CAMPAIGN_ORCHESTRATOR_TICK_SECONDS", 10.0), 5.0), 300.0)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_result: dict[str, Any] = {"status": "not_run"}

    def enabled(self) -> bool:
        return os.getenv("SCHEDULED_CAMPAIGN_ORCHESTRATOR_ENABLED", "0").strip().lower() in _TRUE

    def create_schedule(
        self,
        *,
        experiment_id: str,
        scope: str,
        interval_seconds: int,
        actor: str,
        start_at_ms: int | None = None,
        enabled: bool = True,
    ) -> dict[str, Any]:
        experiment = _approved_testnet_experiment(self.registry, experiment_id)
        clean_scope = _identifier(scope, "scope")
        interval = min(max(int(interval_seconds), 60), 86_400)
        start = _timestamp(start_at_ms)
        schedule_id = "schedule_" + _digest(
            {"experiment_id": experiment["experiment_id"], "scope": clean_scope, "start_at_ms": start}
        )[:32]
        payload = {
            "schedule_id": schedule_id,
            "experiment_id": experiment["experiment_id"],
            "scope": clean_scope,
            "interval_seconds": interval,
            "enabled": bool(enabled),
            "status": "scheduled" if enabled else "disabled",
            "next_run_at_ms": start,
            "last_run_at_ms": 0,
            "last_campaign_id": "",
            "run_count": 0,
            "actor": _identifier(actor, "actor"),
            "created_at_ms": int(time.time() * 1000),
            "updated_at_ms": int(time.time() * 1000),
            "runtime_flags_changed": False,
        }
        self.database.put_json(_SCHEDULE_NAMESPACE, schedule_id, payload, expected_version=0)
        return {**payload, "version": 1}

    def list_schedules(self, *, limit: int = 200) -> list[dict[str, Any]]:
        return [
            {**dict(item["value"]), "version": int(item["version"])}
            for item in list_json_items(
                self.database,
                _SCHEDULE_NAMESPACE,
                limit=min(max(int(limit), 1), 2_000),
                newest_first=True,
            )
        ]

    def tick(self, *, now_ms: int | None = None) -> dict[str, Any]:
        now = _timestamp(now_ms)
        launched: list[str] = []
        updated_campaigns: list[str] = []
        errors: list[str] = []
        for schedule in self.list_schedules(limit=2_000):
            if not schedule.get("enabled") or int(schedule.get("next_run_at_ms", 0)) > now:
                continue
            try:
                campaign = self.campaign.start(
                    experiment_id=schedule["experiment_id"],
                    scope=schedule["scope"],
                    actor="scheduled-campaign-orchestrator",
                    schedule_id=schedule["schedule_id"],
                    now_ms=now,
                )
                launched.append(campaign["campaign_id"])
                campaign = self.campaign.run_cycle(
                    campaign["campaign_id"],
                    actor="scheduled-campaign-orchestrator",
                    now_ms=now,
                )
                updated_campaigns.append(campaign["campaign_id"])
                payload = {
                    **{k: v for k, v in schedule.items() if k != "version"},
                    "status": "active",
                    "last_run_at_ms": now,
                    "last_campaign_id": campaign["campaign_id"],
                    "next_run_at_ms": now + int(schedule["interval_seconds"]) * 1000,
                    "run_count": int(schedule.get("run_count", 0)) + 1,
                    "updated_at_ms": now,
                }
                self.database.put_json(
                    _SCHEDULE_NAMESPACE,
                    schedule["schedule_id"],
                    payload,
                    expected_version=int(schedule["version"]),
                )
            except Exception as exc:
                errors.append(f"{schedule['schedule_id']}: {type(exc).__name__}: {exc}")
        for campaign in self.campaign.list(limit=2_000):
            if campaign["status"] not in _TERMINAL_CAMPAIGNS and campaign["campaign_id"] not in launched:
                try:
                    result = self.campaign.run_cycle(
                        campaign["campaign_id"],
                        actor="scheduled-campaign-orchestrator",
                        now_ms=now,
                    )
                    updated_campaigns.append(result["campaign_id"])
                except Exception as exc:
                    errors.append(f"{campaign['campaign_id']}: {type(exc).__name__}: {exc}")
        self._last_result = {
            "status": "ok" if not errors else "degraded",
            "launched_campaign_ids": launched,
            "updated_campaign_ids": sorted(set(updated_campaigns)),
            "errors": errors,
            "ran_at_ms": now,
            "runtime_flags_changed": False,
        }
        return dict(self._last_result)

    def start(self) -> None:
        if not self.enabled() or (self._thread and self._thread.is_alive()):
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="scheduled-campaign-orchestrator", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=3.0)

    def status(self) -> dict[str, Any]:
        return {
            **self._last_result,
            "enabled": self.enabled(),
            "worker_running": bool(self._thread and self._thread.is_alive()),
            "interval_seconds": self.interval,
            "schedule_count": len(self.list_schedules(limit=2_000)),
            "campaign_count": len(self.campaign.list(limit=2_000)),
        }

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.tick()
            except Exception as exc:
                self._last_result = {
                    "status": "error",
                    "error": f"{type(exc).__name__}: {exc}",
                    "updated_at_ms": int(time.time() * 1000),
                }
            self._stop.wait(self.interval)


class FinalPromotionReportEngine:
    """Create one immutable campaign report for an explicit manual decision."""

    def __init__(self, database: ProjectDatabase | None = None) -> None:
        self.database = database or ProjectDatabase()
        self.database.initialize()
        self.registry = ExperimentRegistry(self.database)
        self.campaigns = TestnetShadowCampaign(self.database)
        self.validations = FillValidationRepository(self.database)
        self.leadership = ChampionChallengerRegistry(self.database)

    def generate(
        self,
        campaign_id: str,
        *,
        actor: str,
        now_ms: int | None = None,
    ) -> dict[str, Any]:
        campaign = self.campaigns.get(campaign_id)
        if campaign is None:
            raise KeyError(campaign_id)
        if campaign["status"] != "completed":
            raise ValueError("final promotion report requires a completed campaign")
        experiment = self.registry.get(campaign["experiment_id"])
        if experiment is None:
            raise KeyError(campaign["experiment_id"])
        evidence = campaign.get("last_evidence") if isinstance(campaign.get("last_evidence"), Mapping) else {}
        validation = evidence.get("fill_validation") if isinstance(evidence.get("fill_validation"), Mapping) else {}
        startup = evidence.get("startup_reconciliation") if isinstance(evidence.get("startup_reconciliation"), Mapping) else {}
        private_stream = evidence.get("private_stream") if isinstance(evidence.get("private_stream"), Mapping) else {}
        gate = PromotionGateEngine().evaluate(
            experiment,
            target_stage=PromotionTarget.TESTNET,
            paper_testnet_validation=validation,
            reconciliation=startup,
            private_stream=private_stream,
        ).to_dict()
        metrics = campaign.get("metrics") if isinstance(campaign.get("metrics"), Mapping) else {}
        campaign_gates = {
            "campaign_completed": campaign["status"] == "completed",
            "minimum_20_matched_fills": int(metrics.get("matched_fill_count", 0)) >= 20,
            "zero_unmatched_paper": int(metrics.get("unmatched_paper_count", 0)) == 0,
            "zero_unmatched_testnet": int(metrics.get("unmatched_testnet_count", 0)) == 0,
            "zero_orphans": int(metrics.get("orphan_execution_count", 0)) == 0,
            "zero_duplicates": int(metrics.get("duplicate_order_count", 0)) == 0,
            "zero_unresolved": int(metrics.get("unresolved_order_count", 0)) == 0,
            "actual_execution_fees": bool(metrics.get("actual_execution_fees")),
            "bounded_10_25_usdt": not bool(
                "campaign_notional_outside_10_25_usdt" in campaign.get("failed_gates", [])
            ),
        }
        failed = sorted(name for name, passed in campaign_gates.items() if not passed)
        eligible = bool(gate.get("automated_gate_passed")) and not failed
        timestamp = _timestamp(now_ms)
        report_payload = {
            "campaign_id": campaign["campaign_id"],
            "experiment_id": campaign["experiment_id"],
            "scope": campaign["scope"],
            "target_stage": "testnet",
            "status": "eligible_for_manual_decision" if eligible else "blocked",
            "eligible_for_manual_decision": eligible,
            "manual_decision_required": True,
            "campaign_gates": campaign_gates,
            "failed_campaign_gates": failed,
            "promotion_gate_report": gate,
            "campaign_metrics": dict(metrics),
            "evidence_sha256": _digest(
                {"campaign": campaign, "promotion_gate_report": gate, "campaign_gates": campaign_gates}
            ),
            "leadership_approval_token": (
                f"PROMOTE:{campaign['scope']}:{campaign['experiment_id']}:testnet"
            ),
            "actor": _identifier(actor, "actor"),
            "created_at_ms": timestamp,
            "runtime_flags_changed": False,
            "mainnet_enabled": False,
        }
        report_id = "promotion_" + _digest(report_payload)[:32]
        report = {"report_id": report_id, **report_payload}
        existing = self.database.get_json(_REPORT_NAMESPACE, report_id)
        if existing is not None:
            return {**dict(existing["value"]), "version": int(existing["version"])}
        version = self.database.put_json(_REPORT_NAMESPACE, report_id, report, expected_version=0)
        self.database.append_event(
            _EVENT_NAMESPACE,
            "final_promotion_report",
            report_id,
            {
                "campaign_id": campaign["campaign_id"],
                "experiment_id": campaign["experiment_id"],
                "eligible": eligible,
                "actor": report_payload["actor"],
            },
            created_at_ms=timestamp,
        )
        return {**report, "version": version}

    def get(self, report_id: str) -> dict[str, Any] | None:
        current = self.database.get_json(_REPORT_NAMESPACE, _identifier(report_id, "report_id"))
        if current is None:
            return None
        return {**dict(current["value"]), "version": int(current["version"])}

    def list(self, *, limit: int = 200) -> list[dict[str, Any]]:
        return [
            {**dict(item["value"]), "version": int(item["version"])}
            for item in list_json_items(
                self.database,
                _REPORT_NAMESPACE,
                limit=min(max(int(limit), 1), 2_000),
                newest_first=True,
            )
        ]


def _approved_testnet_experiment(registry: ExperimentRegistry, experiment_id: str) -> dict[str, Any]:
    experiment = registry.get(_identifier(experiment_id, "experiment_id"))
    if experiment is None:
        raise KeyError(experiment_id)
    promotion = experiment.get("promotion")
    if str(experiment.get("status")) != "promoted" or not isinstance(promotion, Mapping):
        raise ValueError("scheduled campaign requires a promoted experiment")
    if str(promotion.get("status")) != "approved" or str(promotion.get("target_stage")) != "testnet":
        raise ValueError("scheduled campaign requires manual Testnet approval")
    report = promotion.get("report")
    manual = promotion.get("manual_decision")
    if not isinstance(report, Mapping) or not bool(report.get("automated_gate_passed")):
        raise ValueError("scheduled campaign automated evidence is not approved")
    if not isinstance(manual, Mapping) or not bool(manual.get("approved")):
        raise ValueError("scheduled campaign manual approval is missing")
    return experiment


def _timestamp(value: int | None) -> int:
    parsed = int(time.time() * 1000) if value is None else int(value)
    if parsed <= 0:
        raise ValueError("timestamp must be positive")
    return parsed


def _identifier(value: Any, name: str) -> str:
    clean = str(value or "").strip()
    if not clean or len(clean) > 200:
        raise ValueError(f"invalid {name}")
    if any(character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.:-" for character in clean):
        raise ValueError(f"invalid {name}")
    return clean


def _optional_identifier(value: Any, name: str) -> str:
    clean = str(value or "").strip()
    return _identifier(clean, name) if clean else ""


def _digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    ).hexdigest()


def _finite_env(name: str, default: float) -> float:
    try:
        parsed = float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default
    return parsed if math.isfinite(parsed) else default


__all__ = [
    "FinalPromotionReportEngine",
    "ScheduledCampaignOrchestrator",
    "ShadowCampaignPolicy",
    "TestnetShadowCampaign",
]
