"""Versioned live view for Phase 8 campaign operations."""
from __future__ import annotations

import hashlib
import json
import math
import os
import threading
import time
from typing import Any, Mapping

from storage import ProjectDatabase

from .operations import CampaignOperationsService
from .phase7_monitor import Phase7CampaignMonitor
from .phase8_analysis import Phase8PostCampaignAnalyzer

_STATE_NAMESPACE = "phase8_campaign_live"
_EVENT_NAMESPACE = "phase8_campaign_live_events"
_TERMINAL = {"completed", "blocked", "cancelled"}
_TRUE = {"1", "true", "yes", "on"}


class Phase8CampaignLiveView:
    def __init__(
        self,
        database: ProjectDatabase | None = None,
        *,
        operations: CampaignOperationsService | None = None,
        monitor: Phase7CampaignMonitor | None = None,
        analyzer: Phase8PostCampaignAnalyzer | None = None,
    ) -> None:
        self.database = database or ProjectDatabase()
        self.database.initialize()
        self.operations = operations or CampaignOperationsService(self.database)
        self.monitor = monitor or Phase7CampaignMonitor(
            self.database,
            operations=self.operations,
            campaign=self.operations.campaign,
            reports=self.operations.reports,
        )
        self.analyzer = analyzer or Phase8PostCampaignAnalyzer(
            self.database,
            campaign=self.operations.campaign,
            reports=self.operations.reports,
            monitor=self.monitor,
        )
        self.interval = _bounded_float("PHASE8_LIVE_INTERVAL_SECONDS", 1.0, 0.5, 30.0)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.RLock()
        self._state = self._load()

    def enabled(self) -> bool:
        return os.getenv("PHASE8_LIVE_MONITOR_ENABLED", "1").strip().lower() in _TRUE

    def start(self) -> None:
        if not self.enabled() or (self._thread and self._thread.is_alive()):
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="phase8-campaign-live", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5.0)

    def refresh(self, *, now_ms: int | None = None) -> dict[str, Any]:
        timestamp = int(time.time() * 1000) if now_ms is None else int(now_ms)
        with self._lock:
            operations = self.operations.snapshot()
            monitor = self.monitor.refresh(now_ms=timestamp)
            selected = operations.get("active_campaign") or operations.get("latest_campaign") or {}
            campaign_id = str(selected.get("campaign_id") or monitor.get("campaign_id") or "")
            analysis: dict[str, Any] = {}
            analysis_error = ""
            if campaign_id:
                try:
                    campaign_status = str(selected.get("status") or monitor.get("status") or "")
                    if campaign_status in _TERMINAL:
                        analysis = self.analyzer.latest_for_campaign(campaign_id) or self.analyzer.analyze(
                            campaign_id,
                            actor="phase8-auto-analyzer",
                            now_ms=timestamp,
                        )
                    else:
                        analysis = self.analyzer.preview(campaign_id, now_ms=timestamp)
                except (KeyError, RuntimeError, TypeError, ValueError, OSError) as exc:
                    analysis_error = f"{type(exc).__name__}: {exc}"
            alerts = sorted(
                set(
                    [str(value) for value in monitor.get("alerts", [])]
                    + _analysis_alerts(analysis)
                    + (["post_campaign_analysis_error"] if analysis_error else [])
                )
            )
            drawdown = analysis.get("drawdown") if isinstance(analysis.get("drawdown"), Mapping) else {}
            recommendation = analysis.get("recommendation") if isinstance(analysis.get("recommendation"), Mapping) else {}
            material = {
                "campaign_id": campaign_id,
                "campaign_status": str(selected.get("status") or monitor.get("status") or "idle"),
                "monitor": monitor,
                "analysis": analysis,
                "alerts": alerts,
                "drawdown_breached": bool(drawdown.get("breached")),
                "recommendation_action": str(recommendation.get("action") or "PENDING"),
            }
            digest = hashlib.sha256(
                json.dumps(material, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")
            ).hexdigest()
            previous_digest = str(self._state.get("material_sha256") or "")
            sequence = int(self._state.get("sequence", 0) or 0) + int(digest != previous_digest)
            payload = {
                "status": "degraded" if analysis_error else str(material["campaign_status"] or "idle"),
                "campaign_id": campaign_id,
                "checked_at_ms": timestamp,
                "sequence": sequence,
                "material_sha256": digest,
                "changed": digest != previous_digest,
                "operations": operations,
                "monitor": monitor,
                "analysis": analysis,
                "analysis_error": analysis_error,
                "drawdown": dict(drawdown),
                "recommendation": dict(recommendation),
                "alerts": alerts,
                "runtime_flags_changed": False,
                "mainnet_enabled": False,
            }
            self._state = payload
            self._save()
            if digest != previous_digest:
                self.database.append_event(
                    _EVENT_NAMESPACE,
                    "live_state_changed",
                    campaign_id or "campaign-control-plane",
                    {
                        "sequence": sequence,
                        "status": payload["status"],
                        "alerts": alerts,
                        "recommendation": payload["recommendation"].get("action", "PENDING"),
                        "material_sha256": digest,
                    },
                    created_at_ms=timestamp,
                )
            return self.snapshot()

    def snapshot(self, *, since_sequence: int = -1) -> dict[str, Any]:
        with self._lock:
            payload = dict(self._state)
            sequence = int(payload.get("sequence", 0) or 0)
            return {
                **payload,
                "changed_since": sequence > int(since_sequence),
                "enabled": self.enabled(),
                "worker_running": bool(self._thread and self._thread.is_alive()),
                "poll_interval_seconds": self.interval,
                "runtime_flags_changed": False,
                "mainnet_enabled": False,
            }

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.refresh()
            except Exception as exc:  # pragma: no cover - defensive production loop
                with self._lock:
                    self._state = {
                        **self._state,
                        "status": "degraded",
                        "checked_at_ms": int(time.time() * 1000),
                        "analysis_error": f"{type(exc).__name__}: {exc}",
                        "alerts": sorted(set([*self._state.get("alerts", []), "phase8_live_refresh_error"])),
                        "runtime_flags_changed": False,
                        "mainnet_enabled": False,
                    }
                    self._save()
            self._stop.wait(self.interval)

    def _load(self) -> dict[str, Any]:
        current = self.database.get_json(_STATE_NAMESPACE, "current")
        if current and isinstance(current.get("value"), Mapping):
            return dict(current["value"])
        return {
            "status": "idle",
            "campaign_id": "",
            "checked_at_ms": 0,
            "sequence": 0,
            "material_sha256": "",
            "operations": {},
            "monitor": {},
            "analysis": {},
            "drawdown": {},
            "recommendation": {},
            "alerts": [],
            "runtime_flags_changed": False,
            "mainnet_enabled": False,
        }

    def _save(self) -> None:
        current = self.database.get_json(_STATE_NAMESPACE, "current")
        self.database.put_json(
            _STATE_NAMESPACE,
            "current",
            dict(self._state),
            expected_version=int(current["version"]) if current else 0,
        )


def _analysis_alerts(analysis: Mapping[str, Any]) -> list[str]:
    if not analysis:
        return []
    alerts: list[str] = []
    drawdown = analysis.get("drawdown") if isinstance(analysis.get("drawdown"), Mapping) else {}
    recommendation = analysis.get("recommendation") if isinstance(analysis.get("recommendation"), Mapping) else {}
    if bool(drawdown.get("breached")):
        alerts.append("campaign_drawdown_exceeded")
    action = str(recommendation.get("action") or "")
    if action == "REJECT_AND_INVESTIGATE":
        alerts.append("campaign_recommendation_reject")
    elif action == "HOLD_AND_TUNE":
        alerts.append("campaign_recommendation_hold")
    return alerts


def _bounded_float(name: str, default: float, minimum: float, maximum: float) -> float:
    try:
        value = float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        value = default
    if not math.isfinite(value):
        value = default
    return min(max(value, minimum), maximum)


__all__ = ["Phase8CampaignLiveView"]
