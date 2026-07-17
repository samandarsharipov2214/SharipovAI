"""Persistent readiness gate for the read-only Bybit private order stream."""
from __future__ import annotations

import math
import time
from dataclasses import asdict, dataclass
from typing import Any, Mapping

from storage import ProjectDatabase

_NAMESPACE = "bybit_private_ws_health"


@dataclass(frozen=True, slots=True)
class PrivateStreamGateReport:
    environment: str
    required: bool
    ready: bool
    connected: bool
    authenticated: bool
    subscribed: bool
    worker_running: bool
    credentials_configured: bool
    heartbeat_age_ms: int | None
    maximum_heartbeat_age_ms: int
    last_message_at_ms: int
    last_heartbeat_at_ms: int
    last_error: str
    failed_gates: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class PrivateStreamHealthRepository:
    """Store stream health so startup reconciliation can fail closed after restart."""

    def __init__(
        self,
        *,
        database: ProjectDatabase | None = None,
        environment: str = "testnet",
    ) -> None:
        self.database = database or ProjectDatabase()
        self.database.initialize()
        clean = str(environment).strip().lower()
        if clean in {"sandbox", "testnet"}:
            clean = "testnet"
        elif clean in {"live", "mainnet", "live_read_only"}:
            clean = "mainnet"
        else:
            raise ValueError("private stream environment must be testnet or mainnet")
        self.environment = clean

    def record(self, status: Mapping[str, Any], *, recorded_at_ms: int | None = None) -> dict[str, Any]:
        if not isinstance(status, Mapping):
            raise TypeError("private stream status must be an object")
        timestamp = _timestamp(recorded_at_ms)
        document = {
            "environment": self.environment,
            "enabled": bool(status.get("enabled")),
            "worker_running": bool(status.get("worker_running")),
            "credentials_configured": bool(status.get("credentials_configured")),
            "connected": bool(status.get("connected")),
            "authenticated": bool(status.get("authenticated")),
            "subscribed": bool(status.get("subscribed")),
            "last_message_at_ms": _nonnegative_int(status.get("last_message_at_ms")),
            "last_heartbeat_at_ms": _nonnegative_int(
                status.get("last_heartbeat_at_ms") or status.get("last_message_at_ms")
            ),
            "ready_at_ms": _nonnegative_int(status.get("ready_at_ms")),
            "last_error": str(status.get("last_error") or "")[:500],
            "recorded_at_ms": timestamp,
        }
        current = self.database.get_json(_NAMESPACE, self.environment)
        version = int(current["version"]) if current else 0
        new_version = self.database.put_json(
            _NAMESPACE,
            self.environment,
            document,
            expected_version=version,
        )
        return {**document, "version": new_version}

    def snapshot(self) -> dict[str, Any]:
        current = self.database.get_json(_NAMESPACE, self.environment)
        if current is None:
            return {
                "environment": self.environment,
                "enabled": False,
                "worker_running": False,
                "credentials_configured": False,
                "connected": False,
                "authenticated": False,
                "subscribed": False,
                "last_message_at_ms": 0,
                "last_heartbeat_at_ms": 0,
                "ready_at_ms": 0,
                "last_error": "private stream health has not been recorded",
                "recorded_at_ms": 0,
                "version": 0,
            }
        return {**dict(current["value"]), "version": int(current["version"])}

    def evaluate(
        self,
        *,
        required: bool,
        now_ms: int | None = None,
        maximum_heartbeat_age_seconds: float = 60.0,
    ) -> PrivateStreamGateReport:
        maximum_age_ms = int(
            min(max(_finite(maximum_heartbeat_age_seconds, "maximum heartbeat age"), 5.0), 300.0)
            * 1_000
        )
        snapshot = self.snapshot()
        now = _timestamp(now_ms)
        heartbeat = _nonnegative_int(snapshot.get("last_heartbeat_at_ms"))
        heartbeat_age = max(0, now - heartbeat) if heartbeat else None
        failed: list[str] = []
        if required:
            if not bool(snapshot.get("enabled")):
                failed.append("private_order_stream_disabled")
            if not bool(snapshot.get("worker_running")):
                failed.append("private_order_stream_worker_not_running")
            if not bool(snapshot.get("credentials_configured")):
                failed.append("private_order_stream_credentials_missing")
            if not bool(snapshot.get("connected")):
                failed.append("private_order_stream_disconnected")
            if not bool(snapshot.get("authenticated")):
                failed.append("private_order_stream_not_authenticated")
            if not bool(snapshot.get("subscribed")):
                failed.append("private_order_topic_not_subscribed")
            if heartbeat_age is None:
                failed.append("private_order_stream_heartbeat_missing")
            elif heartbeat_age > maximum_age_ms:
                failed.append("private_order_stream_heartbeat_stale")
            if str(snapshot.get("environment")) != self.environment:
                failed.append("private_order_stream_environment_mismatch")
        return PrivateStreamGateReport(
            environment=self.environment,
            required=bool(required),
            ready=not failed,
            connected=bool(snapshot.get("connected")),
            authenticated=bool(snapshot.get("authenticated")),
            subscribed=bool(snapshot.get("subscribed")),
            worker_running=bool(snapshot.get("worker_running")),
            credentials_configured=bool(snapshot.get("credentials_configured")),
            heartbeat_age_ms=heartbeat_age,
            maximum_heartbeat_age_ms=maximum_age_ms,
            last_message_at_ms=_nonnegative_int(snapshot.get("last_message_at_ms")),
            last_heartbeat_at_ms=heartbeat,
            last_error=str(snapshot.get("last_error") or ""),
            failed_gates=tuple(failed),
        )


def _finite(value: Any, name: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed):
        raise ValueError(f"{name} must be finite")
    return parsed


def _nonnegative_int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _timestamp(value: int | None) -> int:
    parsed = int(time.time() * 1000) if value is None else int(value)
    if parsed <= 0:
        raise ValueError("timestamp must be positive")
    return parsed


__all__ = ["PrivateStreamGateReport", "PrivateStreamHealthRepository"]
