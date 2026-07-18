"""Persistent read-only alerts for Phase 8 campaign analysis."""
from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from typing import Any, Callable, Mapping

from storage import ProjectDatabase, list_json_items

_NAMESPACE = "phase8_risk_alerts"
_EVENT_NAMESPACE = "phase8_risk_alert_events"
_TRUE = {"1", "true", "yes", "on"}


class Phase8RiskAlertService:
    def __init__(self, database: ProjectDatabase | None = None) -> None:
        self.database = database or ProjectDatabase()
        self.database.initialize()

    def evaluate(self, snapshot: Mapping[str, Any], *, now_ms: int | None = None) -> dict[str, Any]:
        timestamp = int(time.time() * 1000) if now_ms is None else int(now_ms)
        candidates = _candidates(snapshot)
        active = {row["alert_id"] for row in candidates}
        opened = resolved = 0
        for candidate in candidates:
            current = self.database.get_json(_NAMESPACE, candidate["alert_id"])
            previous = dict(current["value"]) if current else {}
            record = {
                **candidate,
                "status": "open",
                "first_seen_at_ms": int(previous.get("first_seen_at_ms") or timestamp),
                "last_seen_at_ms": timestamp,
                "resolved_at_ms": 0,
                "occurrence_count": int(previous.get("occurrence_count") or 0) + 1,
                "runtime_flags_changed": False,
                "mainnet_enabled": False,
            }
            self.database.put_json(
                _NAMESPACE,
                candidate["alert_id"],
                record,
                expected_version=int(current["version"]) if current else 0,
            )
            if current is None or str(previous.get("status") or "") == "resolved":
                opened += 1
                self._event("opened", record, timestamp)
        for row in self.list(limit=500):
            if str(row.get("status") or "") != "open" or str(row.get("alert_id") or "") in active:
                continue
            current = self.database.get_json(_NAMESPACE, str(row["alert_id"]))
            if current is None:
                continue
            record = {
                **dict(current["value"]),
                "status": "resolved",
                "resolved_at_ms": timestamp,
                "last_seen_at_ms": timestamp,
            }
            self.database.put_json(
                _NAMESPACE,
                str(row["alert_id"]),
                record,
                expected_version=int(current["version"]),
            )
            resolved += 1
            self._event("resolved", record, timestamp)
        result = self.snapshot(limit=100)
        return {
            "status": "ok",
            "evaluated_at_ms": timestamp,
            "candidate_count": len(candidates),
            "opened_count": opened,
            "resolved_count": resolved,
            **result,
        }

    def snapshot(self, *, limit: int = 100) -> dict[str, Any]:
        rows = self.list(limit=limit)
        open_rows = [row for row in rows if str(row.get("status") or "") == "open"]
        return {
            "open_count": len(open_rows),
            "critical_open_count": sum(str(row.get("severity") or "") == "critical" for row in open_rows),
            "open_alerts": open_rows,
            "recent_alerts": rows,
            "runtime_flags_changed": False,
            "mainnet_enabled": False,
        }

    def list(self, *, limit: int = 100) -> list[dict[str, Any]]:
        return [
            {**dict(row["value"]), "version": int(row["version"])}
            for row in list_json_items(
                self.database,
                _NAMESPACE,
                limit=min(max(int(limit), 1), 1_000),
                newest_first=True,
            )
            if isinstance(row.get("value"), Mapping)
        ]

    def _event(self, action: str, record: Mapping[str, Any], timestamp: int) -> None:
        self.database.append_event(
            _EVENT_NAMESPACE,
            "phase8_risk_alert",
            str(record.get("alert_id") or "unknown"),
            {
                "action": action,
                "code": record.get("code"),
                "campaign_id": record.get("campaign_id"),
                "severity": record.get("severity"),
            },
            created_at_ms=timestamp,
        )


class Phase8RiskAlertMonitor:
    def __init__(
        self,
        provider: Callable[[], Mapping[str, Any]],
        service: Phase8RiskAlertService,
    ) -> None:
        self.provider = provider
        self.service = service
        self.interval = _interval()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._last: dict[str, Any] = {"status": "not_run"}

    def enabled(self) -> bool:
        return os.getenv("PHASE8_RISK_ALERTS_ENABLED", "1").strip().lower() in _TRUE

    def tick(self) -> dict[str, Any]:
        self._last = self.service.evaluate(self.provider())
        return dict(self._last)

    def start(self) -> None:
        if not self.enabled() or (self._thread and self._thread.is_alive()):
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="phase8-risk-alerts", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5.0)

    def status(self) -> dict[str, Any]:
        return {
            **self.service.snapshot(limit=100),
            "enabled": self.enabled(),
            "worker_running": bool(self._thread and self._thread.is_alive()),
            "interval_seconds": self.interval,
            "last_result": dict(self._last),
        }

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.tick()
            except Exception as exc:  # pragma: no cover
                self._last = {
                    "status": "error",
                    "error": f"{type(exc).__name__}: {exc}",
                    "updated_at_ms": int(time.time() * 1000),
                }
            self._stop.wait(self.interval)


def _candidates(snapshot: Mapping[str, Any]) -> list[dict[str, Any]]:
    campaign_id = str(snapshot.get("campaign_id") or "campaign-control-plane")
    analysis = snapshot.get("analysis") if isinstance(snapshot.get("analysis"), Mapping) else {}
    drawdown = analysis.get("drawdown") if isinstance(analysis.get("drawdown"), Mapping) else {}
    recommendation = analysis.get("recommendation") if isinstance(analysis.get("recommendation"), Mapping) else {}
    rows: list[tuple[str, str, str, str, dict[str, Any]]] = []
    if bool(drawdown.get("breached")):
        rows.append((
            "campaign_drawdown_exceeded",
            "critical",
            "Campaign drawdown limit exceeded",
            "Observed campaign drawdown is above the Phase 8 limit.",
            {
                "observed_percent": drawdown.get("observed_drawdown_percent"),
                "limit_percent": drawdown.get("limit_percent"),
                "source": drawdown.get("source"),
            },
        ))
    action = str(recommendation.get("action") or "")
    if action == "REJECT_AND_INVESTIGATE":
        rows.append(("campaign_recommendation_reject", "critical", "Campaign requires investigation", str(recommendation.get("reason") or "Quality gates failed."), {"failed_gates": recommendation.get("failed_gates", [])}))
    elif action == "HOLD_AND_TUNE":
        rows.append(("campaign_recommendation_hold", "high", "Campaign requires tuning", str(recommendation.get("reason") or "Quality gates require tuning."), {"failed_gates": recommendation.get("failed_gates", [])}))
    if str(snapshot.get("analysis_error") or ""):
        rows.append(("phase8_analysis_failure", "critical", "Post-campaign analysis failed", "Phase 8 analysis could not be refreshed.", {"error": str(snapshot.get("analysis_error"))[:500]}))
    result: list[dict[str, Any]] = []
    for code, severity, title, message, details in rows:
        fingerprint = hashlib.sha256(
            json.dumps({"code": code, "campaign_id": campaign_id, "details": details}, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        ).hexdigest()[:40]
        result.append({
            "alert_id": f"phase8_alert_{fingerprint}",
            "code": code,
            "severity": severity,
            "title": title,
            "message": message,
            "campaign_id": campaign_id,
            "details": details,
        })
    return result


def _interval() -> float:
    try:
        value = float(os.getenv("PHASE8_RISK_ALERT_INTERVAL_SECONDS", "2"))
    except (TypeError, ValueError):
        value = 2.0
    return min(max(value, 1.0), 300.0)


__all__ = ["Phase8RiskAlertMonitor", "Phase8RiskAlertService"]
