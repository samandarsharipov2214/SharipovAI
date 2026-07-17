"""Persistent, deduplicated critical alerts for campaign operations.

The monitor is read-only with respect to trading authority. It observes canonical
campaign state, persists alert evidence and optionally delivers sanitized notices
to an HTTPS webhook and/or Telegram. It never changes runtime flags, credentials,
orders, campaign state or promotion decisions.
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

_ALERT_NAMESPACE = "critical_alerts"
_ALERT_EVENT_NAMESPACE = "critical_alert_events"
_TRUE = {"1", "true", "yes", "on"}


@dataclass(frozen=True, slots=True)
class AlertCandidate:
    code: str
    severity: str
    title: str
    message: str
    entity_id: str
    details: dict[str, Any]

    @property
    def fingerprint(self) -> str:
        payload = {
            "code": self.code,
            "entity_id": self.entity_id,
            "details": self.details,
        }
        digest = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        ).hexdigest()
        return f"alert_{digest[:40]}"


class CampaignCriticalAlertService:
    """Persist and deliver campaign-critical events with automatic resolution."""

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

    def evaluate(self, operations_snapshot: Mapping[str, Any], *, now_ms: int | None = None) -> dict[str, Any]:
        timestamp = _timestamp(now_ms)
        candidates = _build_candidates(operations_snapshot)
        active_fingerprints = {candidate.fingerprint for candidate in candidates}
        delivered = 0
        created = 0
        reopened = 0
        resolved = 0

        for candidate in candidates:
            fingerprint = candidate.fingerprint
            existing = self.database.get_json(_ALERT_NAMESPACE, fingerprint)
            previous = dict(existing["value"]) if existing else {}
            previous_status = str(previous.get("status") or "")
            should_deliver = (
                existing is None
                or previous_status == "resolved"
                or timestamp - int(previous.get("last_delivered_at_ms") or 0) >= self.cooldown_seconds * 1000
            )
            record = {
                "alert_id": fingerprint,
                "fingerprint": fingerprint,
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
                "delivery": dict(previous.get("delivery") or {}),
                "last_delivered_at_ms": int(previous.get("last_delivered_at_ms") or 0),
            }
            if should_deliver:
                delivery_result = dict(self.delivery(record))
                record["delivery"] = delivery_result
                record["last_delivered_at_ms"] = timestamp
                delivered += 1
            version = int(existing["version"]) if existing else 0
            self.database.put_json(_ALERT_NAMESPACE, fingerprint, record, expected_version=version)
            if existing is None:
                created += 1
                self._event("opened", record, timestamp)
            elif previous_status == "resolved":
                reopened += 1
                self._event("reopened", record, timestamp)

        for row in self._records(limit=1_000):
            if str(row.get("status")) != "open":
                continue
            fingerprint = str(row.get("fingerprint") or row.get("alert_id") or "")
            if not fingerprint or fingerprint in active_fingerprints:
                continue
            existing = self.database.get_json(_ALERT_NAMESPACE, fingerprint)
            if existing is None:
                continue
            record = {
                **dict(existing["value"]),
                "status": "resolved",
                "resolved_at_ms": timestamp,
                "last_seen_at_ms": timestamp,
            }
            self.database.put_json(
                _ALERT_NAMESPACE,
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
                "webhook": bool(os.getenv("ALERT_WEBHOOK_URL", "").strip()),
                "telegram": bool(
                    os.getenv("BOT_TOKEN", "").strip()
                    and os.getenv("ALERT_TELEGRAM_CHAT_ID", "").strip()
                ),
                "enabled": _truthy("ALERT_DELIVERY_ENABLED", default=False),
            },
        }

    def _records(self, *, limit: int) -> list[dict[str, Any]]:
        return [
            {**dict(item["value"]), "version": int(item["version"])}
            for item in list_json_items(
                self.database,
                _ALERT_NAMESPACE,
                limit=min(max(int(limit), 1), 1_000),
                newest_first=True,
            )
        ]

    def _event(self, action: str, record: Mapping[str, Any], timestamp: int) -> None:
        self.database.append_event(
            _ALERT_EVENT_NAMESPACE,
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
        if not _truthy("ALERT_DELIVERY_ENABLED", default=False):
            return {"status": "disabled", "webhook": "disabled", "telegram": "disabled"}
        message = _plain_message(record)
        result: dict[str, Any] = {"status": "attempted", "webhook": "not_configured", "telegram": "not_configured"}

        webhook = os.getenv("ALERT_WEBHOOK_URL", "").strip()
        if webhook:
            result["webhook"] = _post_json(
                webhook,
                {
                    "source": "SharipovAI",
                    "event": "critical_alert",
                    "alert": _sanitized_alert(record),
                },
            )

        token = os.getenv("BOT_TOKEN", "").strip()
        chat_id = os.getenv("ALERT_TELEGRAM_CHAT_ID", "").strip()
        if token and chat_id:
            endpoint = f"https://api.telegram.org/bot{urllib.parse.quote(token, safe=':')}/sendMessage"
            result["telegram"] = _post_json(
                endpoint,
                {
                    "chat_id": chat_id,
                    "text": message,
                    "disable_web_page_preview": True,
                },
            )
        return result


class CampaignCriticalAlertMonitor:
    """Daemon monitor around the canonical Campaign Operations snapshot."""

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
        return _truthy("CRITICAL_ALERT_MONITOR_ENABLED", default=False)

    def tick(self) -> dict[str, Any]:
        snapshot = self.snapshot_provider()
        self._last_result = self.service.evaluate(snapshot)
        return dict(self._last_result)

    def start(self) -> None:
        if not self.enabled() or (self._thread and self._thread.is_alive()):
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="campaign-critical-alert-monitor",
            daemon=True,
        )
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
            except Exception as exc:  # pragma: no cover - defensive production loop
                self._last_result = {
                    "status": "error",
                    "error": f"{type(exc).__name__}: {exc}",
                    "updated_at_ms": int(time.time() * 1000),
                }
            self._stop.wait(self.interval_seconds)


def _build_candidates(snapshot: Mapping[str, Any]) -> list[AlertCandidate]:
    candidates: list[AlertCandidate] = []
    active = snapshot.get("active_campaign") if isinstance(snapshot.get("active_campaign"), Mapping) else {}
    latest = snapshot.get("latest_campaign") if isinstance(snapshot.get("latest_campaign"), Mapping) else {}
    selected = active or latest
    active_count = int(snapshot.get("active_campaign_count") or 0)
    campaign_id = str(selected.get("campaign_id") or "campaign-control-plane")
    plan = snapshot.get("plan") if isinstance(snapshot.get("plan"), Mapping) else {}
    execution = plan.get("execution") if isinstance(plan.get("execution"), Mapping) else {}
    private_stream = plan.get("private_stream") if isinstance(plan.get("private_stream"), Mapping) else {}
    orchestrator = snapshot.get("orchestrator") if isinstance(snapshot.get("orchestrator"), Mapping) else {}

    if active_count > 1:
        candidates.append(
            AlertCandidate(
                code="multiple_active_campaigns",
                severity="critical",
                title="Multiple campaign authorizations detected",
                message="More than one non-terminal Testnet campaign exists; new execution must remain blocked.",
                entity_id="campaign-control-plane",
                details={"active_campaign_count": active_count},
            )
        )

    if active:
        if bool(execution.get("kill_switch", True)):
            candidates.append(
                AlertCandidate(
                    code="kill_switch_engaged_during_campaign",
                    severity="critical",
                    title="Kill switch engaged during active campaign",
                    message="The active campaign cannot safely advance while the execution kill switch is engaged.",
                    entity_id=campaign_id,
                    details={"campaign_id": campaign_id, "kill_switch": True},
                )
            )
        if not bool(execution.get("restart_safe")):
            candidates.append(
                AlertCandidate(
                    code="execution_reconciliation_failure",
                    severity="critical",
                    title="Execution reconciliation is not restart-safe",
                    message="Startup/execution reconciliation blocked the active campaign.",
                    entity_id=campaign_id,
                    details={
                        "campaign_id": campaign_id,
                        "restart_safe": bool(execution.get("restart_safe")),
                        "execution_status": str(execution.get("status") or "unknown"),
                    },
                )
            )
        if not bool(private_stream.get("ready")):
            candidates.append(
                AlertCandidate(
                    code="private_stream_failure",
                    severity="critical",
                    title="Private order/execution stream is not ready",
                    message="Authenticated private execution evidence is unavailable or stale.",
                    entity_id=campaign_id,
                    details={
                        "campaign_id": campaign_id,
                        "private_stream_status": str(private_stream.get("status") or "unknown"),
                    },
                )
            )
    selected_status = str(selected.get("status") or "unknown")
    selected_failed_gates = sorted(str(value) for value in selected.get("failed_gates", []) if value)
    if selected_status == "blocked":
        candidates.append(
            AlertCandidate(
                code="campaign_blocked",
                severity="critical",
                title="Testnet campaign is blocked",
                message="A hard campaign gate blocked further progress; evidence must be investigated before any retry.",
                entity_id=campaign_id,
                details={"campaign_id": campaign_id, "failed_gates": selected_failed_gates},
            )
        )
    identity_gates = [
        gate
        for gate in selected_failed_gates
        if any(token in gate for token in ("orphan", "duplicate", "unresolved", "reconciliation", "notional"))
    ]
    if identity_gates:
        candidates.append(
            AlertCandidate(
                code="campaign_evidence_integrity_failure",
                severity="critical",
                title="Campaign evidence integrity failure",
                message="Orphan, duplicate, unresolved, reconciliation or notional evidence failed.",
                entity_id=campaign_id,
                details={"campaign_id": campaign_id, "failed_gates": identity_gates},
            )
        )

    errors = [str(value) for value in orchestrator.get("errors", []) if value]
    if errors:
        candidates.append(
            AlertCandidate(
                code="campaign_orchestrator_failure",
                severity="critical" if active else "high",
                title="Campaign orchestrator reported failures",
                message="The scheduler/orchestrator returned one or more operational errors.",
                entity_id=campaign_id,
                details={"errors": errors[:20]},
            )
        )
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
        with urllib.request.urlopen(request, timeout=4.0) as response:  # noqa: S310 - validated HTTPS
            status = int(getattr(response, "status", 200))
        return f"sent_http_{status}"
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return f"failed:{type(exc).__name__}"


def _sanitized_alert(record: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: record.get(key)
        for key in (
            "alert_id",
            "code",
            "severity",
            "title",
            "message",
            "entity_id",
            "details",
            "status",
            "first_seen_at_ms",
            "last_seen_at_ms",
            "occurrence_count",
        )
    }


def _plain_message(record: Mapping[str, Any]) -> str:
    severity = str(record.get("severity") or "critical").upper()
    title = str(record.get("title") or "SharipovAI alert")
    message = str(record.get("message") or "")
    entity = str(record.get("entity_id") or "system")
    return f"[{severity}] SharipovAI\n{title}\n{message}\nEntity: {entity}"


def _timestamp(value: int | None) -> int:
    parsed = int(time.time() * 1000) if value is None else int(value)
    if parsed <= 0:
        raise ValueError("timestamp must be positive")
    return parsed


def _truthy(name: str, *, default: bool) -> bool:
    fallback = "1" if default else "0"
    return os.getenv(name, fallback).strip().lower() in _TRUE


def _bounded_float(name: str, default: float, minimum: float, maximum: float) -> float:
    try:
        value = float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return min(max(value, minimum), maximum)


__all__ = [
    "AlertCandidate",
    "CampaignCriticalAlertMonitor",
    "CampaignCriticalAlertService",
]
