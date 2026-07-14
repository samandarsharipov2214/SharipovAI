"""Non-overlapping schedule state machine for approved Testnet campaigns."""
from __future__ import annotations

import hashlib
import json
import math
import os
import threading
import time
from typing import Any, Mapping

from experiments.registry import ExperimentRegistry
from storage import ProjectDatabase, list_json_items

from .core import TestnetShadowCampaign

_SCHEDULE_NAMESPACE = "scheduled_campaign_schedules"
_TERMINAL = {"completed", "blocked", "cancelled"}
_TRUE = {"1", "true", "yes", "on"}


class ScheduledCampaignOrchestrator:
    """Run at most one global Testnet shadow campaign at a time."""

    def __init__(
        self,
        database: ProjectDatabase | None = None,
        *,
        campaign: TestnetShadowCampaign | Any | None = None,
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
            {
                "experiment_id": experiment["experiment_id"],
                "scope": clean_scope,
                "start_at_ms": start,
            }
        )[:32]
        timestamp = int(time.time() * 1000)
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
            "created_at_ms": timestamp,
            "updated_at_ms": timestamp,
            "runtime_flags_changed": False,
        }
        version = self.database.put_json(
            _SCHEDULE_NAMESPACE,
            schedule_id,
            payload,
            expected_version=0,
        )
        return {**payload, "version": version}

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
        updated: list[str] = []
        deferred: list[str] = []
        errors: list[str] = []

        campaign_rows = self.campaign.list(limit=2_000)
        active = [item for item in campaign_rows if str(item.get("status")) not in _TERMINAL]
        # Advance existing campaigns before considering new schedules.
        for item in active:
            try:
                result = self.campaign.run_cycle(
                    str(item["campaign_id"]),
                    actor="scheduled-campaign-orchestrator",
                    now_ms=now,
                )
                updated.append(str(result["campaign_id"]))
            except Exception as exc:
                errors.append(f"{item['campaign_id']}: {type(exc).__name__}: {exc}")

        refreshed = self.campaign.list(limit=2_000)
        active = [item for item in refreshed if str(item.get("status")) not in _TERMINAL]
        if len(active) > 1:
            errors.append("multiple non-terminal campaigns detected; new launches blocked")

        for schedule in sorted(
            self.list_schedules(limit=2_000),
            key=lambda item: (int(item.get("next_run_at_ms", 0)), str(item.get("schedule_id", ""))),
        ):
            if not schedule.get("enabled") or int(schedule.get("next_run_at_ms", 0)) > now:
                continue
            last_id = str(schedule.get("last_campaign_id") or "")
            last = next(
                (item for item in refreshed if str(item.get("campaign_id")) == last_id),
                None,
            )
            if last is not None and str(last.get("status")) not in _TERMINAL:
                deferred.append(str(schedule["schedule_id"]))
                self._defer(schedule, now=now, reason="previous_campaign_non_terminal")
                continue
            if active:
                deferred.append(str(schedule["schedule_id"]))
                self._defer(schedule, now=now, reason="global_campaign_authorization_busy")
                continue
            try:
                created = self.campaign.start(
                    experiment_id=str(schedule["experiment_id"]),
                    scope=str(schedule["scope"]),
                    actor="scheduled-campaign-orchestrator",
                    schedule_id=str(schedule["schedule_id"]),
                    now_ms=now,
                )
                launched.append(str(created["campaign_id"]))
                result = self.campaign.run_cycle(
                    str(created["campaign_id"]),
                    actor="scheduled-campaign-orchestrator",
                    now_ms=now,
                )
                updated.append(str(result["campaign_id"]))
                active = [result] if str(result.get("status")) not in _TERMINAL else []
                self._record_launch(schedule, campaign_id=str(created["campaign_id"]), now=now)
            except Exception as exc:
                errors.append(f"{schedule['schedule_id']}: {type(exc).__name__}: {exc}")
                self._record_error(schedule, now=now, error=f"{type(exc).__name__}: {exc}")

        self._last_result = {
            "status": "ok" if not errors else "degraded",
            "launched_campaign_ids": launched,
            "updated_campaign_ids": sorted(set(updated)),
            "deferred_schedule_ids": sorted(set(deferred)),
            "errors": errors,
            "ran_at_ms": now,
            "global_non_terminal_campaign_count": len(active),
            "runtime_flags_changed": False,
            "mainnet_enabled": False,
        }
        return dict(self._last_result)

    def start(self) -> None:
        if not self.enabled() or (self._thread and self._thread.is_alive()):
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="scheduled-campaign-orchestrator",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=3.0)

    def status(self) -> dict[str, Any]:
        campaigns = self.campaign.list(limit=2_000)
        return {
            **self._last_result,
            "enabled": self.enabled(),
            "worker_running": bool(self._thread and self._thread.is_alive()),
            "interval_seconds": self.interval,
            "schedule_count": len(self.list_schedules(limit=2_000)),
            "campaign_count": len(campaigns),
            "non_terminal_campaign_count": sum(
                str(item.get("status")) not in _TERMINAL for item in campaigns
            ),
            "single_global_campaign_authorization": True,
        }

    def _defer(self, schedule: Mapping[str, Any], *, now: int, reason: str) -> None:
        interval_ms = int(schedule["interval_seconds"]) * 1000
        payload = {
            **{key: value for key, value in schedule.items() if key != "version"},
            "status": "deferred",
            "last_deferred_reason": reason,
            "next_run_at_ms": now + interval_ms,
            "updated_at_ms": now,
        }
        self.database.put_json(
            _SCHEDULE_NAMESPACE,
            str(schedule["schedule_id"]),
            payload,
            expected_version=int(schedule["version"]),
        )

    def _record_launch(self, schedule: Mapping[str, Any], *, campaign_id: str, now: int) -> None:
        payload = {
            **{key: value for key, value in schedule.items() if key != "version"},
            "status": "active",
            "last_run_at_ms": now,
            "last_campaign_id": campaign_id,
            "next_run_at_ms": now + int(schedule["interval_seconds"]) * 1000,
            "run_count": int(schedule.get("run_count", 0)) + 1,
            "updated_at_ms": now,
            "last_error": "",
        }
        self.database.put_json(
            _SCHEDULE_NAMESPACE,
            str(schedule["schedule_id"]),
            payload,
            expected_version=int(schedule["version"]),
        )

    def _record_error(self, schedule: Mapping[str, Any], *, now: int, error: str) -> None:
        payload = {
            **{key: value for key, value in schedule.items() if key != "version"},
            "status": "error",
            "last_error": error[:1_000],
            "next_run_at_ms": now + int(schedule["interval_seconds"]) * 1000,
            "updated_at_ms": now,
        }
        self.database.put_json(
            _SCHEDULE_NAMESPACE,
            str(schedule["schedule_id"]),
            payload,
            expected_version=int(schedule["version"]),
        )

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


def _approved_testnet_experiment(registry: ExperimentRegistry, experiment_id: str) -> dict[str, Any]:
    clean = _identifier(experiment_id, "experiment_id")
    experiment = registry.get(clean)
    if experiment is None:
        raise KeyError(clean)
    promotion = experiment.get("promotion")
    if str(experiment.get("status")) != "promoted" or not isinstance(promotion, Mapping):
        raise ValueError("scheduled campaign requires a promoted experiment")
    if str(promotion.get("status")) != "approved" or str(promotion.get("target_stage")) != "testnet":
        raise ValueError("scheduled campaign requires manual Testnet approval")
    report = promotion.get("report")
    manual = promotion.get("manual_decision")
    if not isinstance(report, Mapping) or not bool(report.get("automated_gate_passed")):
        raise ValueError("scheduled campaign automated evidence is not approved")
    if report.get("failed_gates"):
        raise ValueError("scheduled campaign promotion report contains failed gates")
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


def _finite_env(name: str, default: float) -> float:
    try:
        parsed = float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default
    return parsed if math.isfinite(parsed) else default


__all__ = ["ScheduledCampaignOrchestrator"]
