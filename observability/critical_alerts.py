"""Persistent, deduplicated critical alerts for bounded campaign operations.

Alerts are observation authority only. They never change credentials, flags, the
kill switch, campaign state, decisions, capital or Mainnet availability.
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable, Mapping

from storage import ProjectDatabase, list_json_items

_NAMESPACE = "critical_campaign_alerts"
_EVENT_NAMESPACE = "critical_campaign_alert_events"
_TRUE = {"1", "true", "yes", "on"}


@dataclass(frozen=True, slots=True)
class _Candidate:
    code: str
    title: str
    message: str
    entity_id: str
    details: dict[str, Any]
    severity: str = "critical"

    @property
    def fingerprint(self) -> str:
        body = json.dumps(
            {"code": self.code, "entity_id": self.entity_id, "details": self.details},
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        return "alert_" + hashlib.sha256(body.encode("utf-8")).hexdigest()[:40]


class CampaignCriticalAlertService:
    def __init__(
        self,
        database: ProjectDatabase | None = None,
        *,
        delivery: Callable[[Mapping[str, Any]], Mapping[str, Any]] | None = None,
    ) -> None:
        self.database = database or ProjectDatabase()
        self.database.initialize()
        self.delivery = delivery or self._deliver
        self.cooldown_seconds = _bounded_float("CRITICAL_ALERT_REPEAT_SECONDS", 900.0, 60.0, 86_400.0)

    def evaluate(self, snapshot: Mapping[str, Any], *, now_ms: int | None = None) -> dict[str, Any]:
        timestamp = _timestamp(now_ms)
        candidates = _candidates(snapshot)
        active = {candidate.fingerprint for candidate in candidates}
        created = delivered = resolved = reopened = 0

        for candidate in candidates:
            existing = self.database.get_json(_NAMESPACE, candidate.fingerprint)
            previous = dict(existing["value"]) if existing else {}
            previous_status = str(previous.get("status") or "")
            should_deliver = (
                existing is None
                or previous_status == "resolved"
                or timestamp - int(previous.get("last_delivered_at_ms") or 0) >= self.cooldown_seconds * 1000
            )
            record = {
                "alert_id": candidate.fingerprint,
                "fingerprint": candidate.fingerprint,
                "code": candidate.code,
                "severity": candidate.severity,
                "title": candidate.title,
                "message": candidate.message,
                "entity_id": candidate.entity_id,
                "details": candidate.details,
                "status": "open",
                "first_seen_at_ms": int(previous.get("first_seen_at_ms") or timestamp),
                "last_seen_at_ms": timestamp,
                "resolved_at_ms": 0,
                "occurrence_count": int(previous.get("occurrence_count") or 0) + 1,
                "last_delivered_at_ms": int(previous.get("last_delivered_at_ms") or 0),
                "delivery": dict(previous.get("delivery") or {}),
            }
            if should_deliver:
                record["delivery"] = dict(self.delivery(record))
                record["last_delivered_at_ms"] = timestamp
                delivered += 1
            self.database.put_json(
                _NAMESPACE,
                candidate.fingerprint,
                record,
                expected_version=int(existing["version"]) if existing else 0,
            )
            if existing is None:
                created += 1
                self._event("opened", record, timestamp)
            elif previous_status == "resolved":
                reopened += 1
                self._event("reopened", record, timestamp)

        for row in self._records(limit=1_000):
            if str(row.get("status")) != "open":
                continue
            fingerprint = str(row.get("fingerprint") or "")
            if not fingerprint or fingerprint in active:
                continue
            existing = self.database.get_json(_NAMESPACE, fingerprint)
            if existing is None:
                continue
            record = {
                **dict(existing["value"]),
                "status": "resolved",
                "resolved_at_ms": timestamp,
                "last_seen_at_ms": timestamp,
            }
            self.database.put_json(
                _NAMESPACE,
                fingerprint,
                record,
                expected_version=int(existing["version"]),
            )
            resolved += 1
            self._event("resolved", record, timestamp)

        return {
            "status": "ok",
            "evaluated_at_ms": timestamp,
            "candidate_count": len(candidates),
            "created_count": created,
            "reopened_count": reopened,
            "resolved_count": resolved,
            "delivered_count": delivered,
            **self.snapshot(limit=100),
        }

    def snapshot(self, *, limit: int = 100) -> dict[str, Any]:
        records = self._records(limit=limit)
        open_alerts = [row for row in records if str(row.get("status")) == "open"]
        return {
            "open_count": len(open_alerts),
            "critical_open_count": sum(str(row.get("severity")) == "critical" for row in open_alerts),
            "open_alerts": open_alerts,
            "recent_alerts": records[: min(max(int(limit), 1), 100)],
            "delivery_configured": {
                "enabled": _truthy("ALERT_DELIVERY_ENABLED", False),
                "webhook": bool(os.getenv("ALERT_WEBHOOK_URL", "").strip()),
                "telegram": bool(os.getenv("BOT_TOKEN", "").strip() and os.getenv("ALERT_TELEGRAM_CHAT_ID", "").strip()),
            },
        }

    def _records(self, *, limit: int) -> list[dict[str, Any]]:
        return [
            {**dict(item["value"]), "version": int(item["version"])}
            for item in list_json_items(
                self.database,
                _NAMESPACE,
                limit=min(max(int(limit), 1), 1_000),
                newest_first=True,
            )
        ]

    def _event(self, action: str, record: Mapping[str, Any], timestamp: int) -> None:
        self.database.append_event(
            _EVENT_NAMESPACE,
            "critical_alert",
            str(record.get("alert_id") or "unknown"),
            {
                "action": action,
                "code": record.get("code"),
                "severity": record.get("severity"),
                "entity_id": record.get("entity_id"),
                "delivery": record.get("delivery", {}),
            },
            created_at_ms=timestamp,
        )

    def _deliver(self, record: Mapping[str, Any]) -> Mapping[str, Any]:
        if not _truthy("ALERT_DELIVERY_ENABLED", False):
            return {"status": "disabled", "webhook": "disabled", "telegram": "disabled"}
        result: dict[str, str] = {"status": "attempted", "webhook": "not_configured", "telegram": "not_configured"}
        webhook = os.getenv("ALERT_WEBHOOK_URL", "").strip()
        if webhook:
            result["webhook"] = _post_json(webhook, {"source": "SharipovAI", "event": "critical_alert", "alert": _sanitized(record)})
        token = os.getenv("BOT_TOKEN", "").strip()
        chat_id = os.getenv("ALERT_TELEGRAM_CHAT_ID", "").strip()
        if token and chat_id:
            endpoint = f"https://api.telegram.org/bot{urllib.parse.quote(token, safe=':')}/sendMessage"
            result["telegram"] = _post_json(endpoint, {"chat_id": chat_id, "text": _message(record), "disable_web_page_preview": True})
        return result


class CampaignCriticalAlertMonitor:
    def __init__(
        self,
        snapshot_provider: Callable[[], Mapping[str, Any]],
        service: CampaignCriticalAlertService,
    ) -> None:
        self.snapshot_provider = snapshot_provider
        self.service = service
        self.interval_seconds = _bounded_float("CRITICAL_ALERT_MONITOR_SECONDS", 15.0, 5.0, 300.0)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_result: dict[str, Any] = {"status": "not_run"}

    def enabled(self) -> bool:
        return _truthy("CRITICAL_ALERT_MONITOR_ENABLED", False)

    def tick(self) -> dict[str, Any]:
        self._last_result = self.service.evaluate(self.snapshot_provider())
        return dict(self._last_result)

    def start(self) -> None:
        if not self.enabled() or (self._thread and self._thread.is_alive()):
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="campaign-critical-alert-monitor", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3.0)

    def status(self) -> dict[str, Any]:
        return {
            **self.service.snapshot(limit=100),
            "monitor_enabled": self.enabled(),
            "worker_running": bool(self._thread and self._thread.is_alive()),
            "interval_seconds": self.interval_seconds,
            "last_result": dict(self._last_result),
        }

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.tick()
            except Exception as exc:  # pragma: no cover
                self._last_result = {
                    "status": "error",
                    "error": f"{type(exc).__name__}: {exc}",
                    "updated_at_ms": int(time.time() * 1000),
                }
            self._stop.wait(self.interval_seconds)


def _candidates(snapshot: Mapping[str, Any]) -> list[_Candidate]:
    candidates: list[_Candidate] = []
    active = snapshot.get("active_campaign") if isinstance(snapshot.get("active_campaign"), Mapping) else {}
    latest = snapshot.get("latest_campaign") if isinstance(snapshot.get("latest_campaign"), Mapping) else {}
    selected = active or latest
    campaign_id = str(selected.get("campaign_id") or "campaign-control-plane")
    plan = snapshot.get("plan") if isinstance(snapshot.get("plan"), Mapping) else {}
    execution = plan.get("execution") if isinstance(plan.get("execution"), Mapping) else {}
    private_stream = plan.get("private_stream") if isinstance(plan.get("private_stream"), Mapping) else {}
    orchestrator = snapshot.get("orchestrator") if isinstance(snapshot.get("orchestrator"), Mapping) else {}
    phase7 = snapshot.get("phase7_monitor") if isinstance(snapshot.get("phase7_monitor"), Mapping) else {}

    active_count = int(snapshot.get("active_campaign_count") or 0)
    if active_count > 1:
        candidates.append(_Candidate("multiple_active_campaigns", "Multiple campaign authorizations", "More than one non-terminal campaign exists; execution must remain blocked.", "campaign-control-plane", {"active_campaign_count": active_count}))
    if active and bool(execution.get("kill_switch", True)):
        candidates.append(_Candidate("kill_switch_engaged_during_campaign", "Kill switch engaged during active campaign", "The active campaign cannot safely advance while the execution kill switch is engaged.", campaign_id, {"kill_switch": True}))
    if active and not bool(execution.get("restart_safe")):
        candidates.append(_Candidate("execution_reconciliation_failure", "Execution reconciliation is not restart-safe", "Startup/execution reconciliation blocked the active campaign.", campaign_id, {"execution_status": str(execution.get("status") or "unknown")}))
    if active and not bool(private_stream.get("ready")):
        candidates.append(_Candidate("private_stream_failure", "Private execution stream is not ready", "Authenticated order/execution evidence is unavailable or stale.", campaign_id, {"private_stream_status": str(private_stream.get("status") or "unknown")}))
    if bool(phase7.get("heartbeat_stale")):
        candidates.append(_Candidate("phase7_monitor_heartbeat_stale", "Phase 7 monitor heartbeat is stale", "Campaign evidence projection is no longer refreshing inside the allowed window.", campaign_id, {"heartbeat_age_seconds": phase7.get("heartbeat_age_seconds")}))

    failed = sorted(str(value) for value in selected.get("failed_gates", []) if value)
    if str(selected.get("status") or "") == "blocked":
        candidates.append(_Candidate("campaign_blocked", "Testnet campaign is blocked", "A hard gate blocked further progress; investigate canonical evidence before any retry.", campaign_id, {"failed_gates": failed}))
    identity = [gate for gate in failed if any(token in gate for token in ("orphan", "duplicate", "unresolved", "reconciliation", "notional"))]
    if identity:
        candidates.append(_Candidate("campaign_evidence_integrity_failure", "Campaign evidence integrity failure", "Orphan, duplicate, unresolved, reconciliation or notional evidence failed.", campaign_id, {"failed_gates": identity}))
    errors = [str(value) for value in orchestrator.get("errors", []) if value]
    if errors:
        candidates.append(_Candidate("campaign_orchestrator_failure", "Campaign orchestrator failure", "The scheduler/orchestrator returned operational errors.", campaign_id, {"errors": errors[:20]}, "critical" if active else "high"))
    return candidates


def _post_json(url: str, payload: Mapping[str, Any]) -> str:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or not parsed.netloc:
        return "blocked_non_https_url"
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8"),
        headers={"Content-Type": "application/json", "User-Agent": "SharipovAI-Alerting/1"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=4.0) as response:  # noqa: S310
            return f"sent_http_{int(getattr(response, 'status', 200))}"
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return f"failed:{type(exc).__name__}"


def _sanitized(record: Mapping[str, Any]) -> dict[str, Any]:
    return {key: record.get(key) for key in ("alert_id", "code", "severity", "title", "message", "entity_id", "details", "status", "first_seen_at_ms", "last_seen_at_ms", "occurrence_count")}


def _message(record: Mapping[str, Any]) -> str:
    return f"[{str(record.get('severity') or 'critical').upper()}] SharipovAI\n{record.get('title')}\n{record.get('message')}\nEntity: {record.get('entity_id')}"


def _timestamp(value: int | None) -> int:
    parsed = int(time.time() * 1000) if value is None else int(value)
    if parsed <= 0:
        raise ValueError("timestamp must be positive")
    return parsed


def _truthy(name: str, default: bool) -> bool:
    return os.getenv(name, "1" if default else "0").strip().lower() in _TRUE


def _bounded_float(name: str, default: float, minimum: float, maximum: float) -> float:
    try:
        value = float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return min(max(value, minimum), maximum)


__all__ = ["CampaignCriticalAlertMonitor", "CampaignCriticalAlertService"]
