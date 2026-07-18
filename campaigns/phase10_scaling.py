"""Controlled Testnet scaling and immutable performance evidence.

The module creates authorization records only. It never submits an order, changes
runtime flags, disables the kill switch, or enables Mainnet execution.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

from storage import ProjectDatabase, VersionConflict, list_json_items

_ACTIVATIONS_NS = "phase10_scaling_activations"
_SNAPSHOTS_NS = "phase10_performance_snapshots"
_MONTHLY_NS = "phase10_monthly_reports"
_CONFIRMATION = "I_APPROVE_CONTROLLED_TESTNET_NOTIONAL_SCALING"
_SCOPE_RE = re.compile(r"^[A-Z0-9]{3,32}$")
_MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


@dataclass(frozen=True, slots=True)
class ScalingExecutionPolicy:
    maximum_notional_usdt: float = 50.0
    maximum_step_multiplier: float = 1.5
    activation_ttl_seconds: int = 86400
    minimum_approved_campaigns: int = 2
    maximum_drawdown_bps: float = 250.0

    def __post_init__(self) -> None:
        maximum = _required_finite(self.maximum_notional_usdt, "maximum_notional_usdt")
        multiplier = _required_finite(self.maximum_step_multiplier, "maximum_step_multiplier")
        drawdown = _required_finite(self.maximum_drawdown_bps, "maximum_drawdown_bps")
        if not 0 < maximum <= 50:
            raise ValueError("maximum_notional_usdt must be within (0, 50]")
        if not 1 < multiplier <= 2:
            raise ValueError("maximum_step_multiplier must be within (1, 2]")
        if not 60 <= int(self.activation_ttl_seconds) <= 7 * 86400:
            raise ValueError("activation_ttl_seconds must be between 60 seconds and 7 days")
        if int(self.minimum_approved_campaigns) < 2:
            raise ValueError("minimum_approved_campaigns must be at least 2")
        if drawdown < 0:
            raise ValueError("maximum_drawdown_bps must be non-negative")


class ControlledScalingService:
    """Creates bounded, expiring and integrity-protected Testnet authority."""

    def __init__(
        self,
        database: ProjectDatabase | None = None,
        *,
        policy: ScalingExecutionPolicy | None = None,
    ) -> None:
        self.database = database or ProjectDatabase()
        self.database.initialize()
        self.policy = policy or ScalingExecutionPolicy()

    def activate(
        self,
        plan: Mapping[str, Any],
        *,
        actor: str,
        confirmation: str,
        scope: str = "BTCUSDT",
        now_ms: int | None = None,
    ) -> dict[str, Any]:
        actor = _required_text(actor, "actor", maximum_length=128)
        scope = _required_text(scope, "scope", maximum_length=32).upper()
        if not _SCOPE_RE.fullmatch(scope):
            raise ValueError("scope must be an uppercase exchange symbol")
        if confirmation != _CONFIRMATION:
            raise ValueError("exact scaling confirmation is required")
        if not isinstance(plan, Mapping):
            raise ValueError("scaling plan must be a mapping")
        plan_id = _required_text(plan.get("plan_id"), "plan_id", maximum_length=128)
        if str(plan.get("status") or "") != "eligible_for_manual_scaling_review":
            raise ValueError("scaling plan is not eligible")
        if list(plan.get("failed_gates") or []):
            raise ValueError("scaling plan contains failed gates")
        gates = plan.get("gates")
        if isinstance(gates, Mapping) and any(value is not True for value in gates.values()):
            raise ValueError("scaling plan contains a non-passing gate")

        campaign_ids = sorted(
            {
                _required_text(item, "campaign_id", maximum_length=128)
                for item in (plan.get("campaign_ids") or [])
            }
        )
        if len(campaign_ids) < self.policy.minimum_approved_campaigns:
            raise ValueError("insufficient approved campaigns")

        current = _required_finite(plan.get("current_notional_usdt"), "current_notional_usdt")
        proposed = _required_finite(plan.get("proposed_next_notional_usdt"), "proposed_next_notional_usdt")
        ceiling = min(self.policy.maximum_notional_usdt, current * self.policy.maximum_step_multiplier)
        if current <= 0 or proposed <= current or proposed > ceiling:
            raise ValueError("proposed notional violates controlled step policy")

        evidence = plan.get("evidence") if isinstance(plan.get("evidence"), Mapping) else {}
        drawdown = _required_finite(evidence.get("maximum_drawdown_bps", 0.0), "maximum_drawdown_bps")
        if drawdown < 0 or drawdown > self.policy.maximum_drawdown_bps:
            raise ValueError("drawdown exceeds activation policy")

        timestamp = _timestamp_ms(now_ms)
        for existing in self.active_activations(now_ms=timestamp):
            raise ValueError(f"active scaling authority already exists: {existing['activation_id']}")

        expires_at_ms = timestamp + int(self.policy.activation_ttl_seconds) * 1000
        activation = {
            "schema_version": 2,
            "plan_id": plan_id,
            "campaign_ids": campaign_ids,
            "scope": scope,
            "actor": actor,
            "created_at_ms": timestamp,
            "expires_at_ms": expires_at_ms,
            "status": "active",
            "previous_notional_usdt": current,
            "authorized_notional_usdt": proposed,
            "execution_environment": "testnet",
            "single_canonical_execution_path": True,
            "kill_switch_override": False,
            "mainnet_enabled": False,
        }
        activation["authority_hash"] = _authority_hash(activation)
        activation_id = "p10a_" + activation["authority_hash"][:32]
        activation["activation_id"] = activation_id
        self.database.put_json(_ACTIVATIONS_NS, activation_id, activation, expected_version=0)
        self.database.append_event(
            _ACTIVATIONS_NS,
            "scaling_activated",
            activation_id,
            activation,
            created_at_ms=timestamp,
        )
        return activation

    def revoke(
        self,
        activation_id: str,
        *,
        actor: str,
        reason: str,
        now_ms: int | None = None,
    ) -> dict[str, Any]:
        activation_id = _required_text(activation_id, "activation_id", maximum_length=128)
        actor = _required_text(actor, "actor", maximum_length=128)
        reason = _required_text(reason, "reason", maximum_length=1000)
        row = self.database.get_json(_ACTIVATIONS_NS, activation_id)
        if row is None:
            raise ValueError("activation not found")
        activation = dict(row["value"])
        if not _integrity_valid(activation):
            raise ValueError("activation integrity check failed")
        if activation.get("status") == "revoked":
            return activation
        if activation.get("status") != "active":
            raise ValueError("activation is not active")
        timestamp = _timestamp_ms(now_ms)
        activation.update(
            {
                "status": "revoked",
                "revoked_at_ms": timestamp,
                "revoked_by": actor,
                "revoke_reason": reason,
            }
        )
        self.database.put_json(
            _ACTIVATIONS_NS,
            activation_id,
            activation,
            expected_version=int(row["version"]),
        )
        self.database.append_event(
            _ACTIVATIONS_NS,
            "scaling_revoked",
            activation_id,
            activation,
            created_at_ms=timestamp,
        )
        return activation

    def validate_authority(
        self,
        activation_id: str,
        *,
        scope: str,
        requested_notional_usdt: float,
        now_ms: int | None = None,
    ) -> dict[str, Any]:
        row = self.database.get_json(_ACTIVATIONS_NS, str(activation_id))
        if row is None:
            return {"allowed": False, "reason": "activation_not_found", "failed_checks": ["exists"]}
        activation = dict(row["value"])
        timestamp = _timestamp_ms(now_ms)
        requested = _optional_finite(requested_notional_usdt)
        authorized = _optional_finite(activation.get("authorized_notional_usdt"))
        expires = _optional_int(activation.get("expires_at_ms"))
        checks = {
            "integrity": _integrity_valid(activation),
            "active": activation.get("status") == "active",
            "not_expired": expires is not None and timestamp < expires,
            "scope_matches": str(scope).strip().upper() == str(activation.get("scope") or "").upper(),
            "within_notional": requested is not None and authorized is not None and 0 < requested <= authorized,
            "within_absolute_ceiling": authorized is not None and 0 < authorized <= self.policy.maximum_notional_usdt,
            "testnet_only": activation.get("execution_environment") == "testnet",
            "canonical_path_only": activation.get("single_canonical_execution_path") is True,
            "kill_switch_not_overridden": activation.get("kill_switch_override") is False,
            "mainnet_locked": activation.get("mainnet_enabled") is False,
        }
        failed = sorted(name for name, passed in checks.items() if not passed)
        return {
            "allowed": not failed,
            "failed_checks": failed,
            "checks": checks,
            "activation": activation,
        }

    def record_snapshot(
        self,
        metrics: Mapping[str, Any],
        *,
        captured_at_ms: int | None = None,
    ) -> dict[str, Any]:
        if not isinstance(metrics, Mapping):
            raise ValueError("metrics must be a mapping")
        campaign_id = _required_text(metrics.get("campaign_id"), "campaign_id", maximum_length=128)
        normalized = dict(metrics)
        for key in ("net_pnl_usdt", "fees_usdt", "maximum_drawdown_bps"):
            normalized[key] = _required_finite(normalized.get(key, 0.0), key)
        normalized["matched_fill_count"] = _required_non_negative_int(
            normalized.get("matched_fill_count", 0), "matched_fill_count"
        )
        if normalized["fees_usdt"] < 0 or normalized["maximum_drawdown_bps"] < 0:
            raise ValueError("fees and drawdown must be non-negative")
        timestamp = _timestamp_ms(captured_at_ms)
        material = _canonical_json({"captured_at_ms": timestamp, "campaign_id": campaign_id, "metrics": normalized})
        evidence_hash = hashlib.sha256(material).hexdigest()
        snapshot_id = "p10p_" + evidence_hash[:32]
        payload = {
            "schema_version": 2,
            "snapshot_id": snapshot_id,
            "captured_at_ms": timestamp,
            "metrics": normalized,
            "evidence_sha256": evidence_hash,
            "mainnet_enabled": False,
        }
        existing = self.database.get_json(_SNAPSHOTS_NS, snapshot_id)
        if existing:
            if existing["value"] != payload:
                raise VersionConflict("snapshot identity collision")
            return dict(existing["value"])
        self.database.put_json(_SNAPSHOTS_NS, snapshot_id, payload, expected_version=0)
        self.database.append_event(
            _SNAPSHOTS_NS,
            "performance_snapshot",
            snapshot_id,
            payload,
            created_at_ms=timestamp,
        )
        return payload

    def monthly_report(
        self,
        snapshots: Sequence[Mapping[str, Any]],
        *,
        month: str,
        generated_at_ms: int | None = None,
    ) -> dict[str, Any]:
        month = _required_text(month, "month", maximum_length=7)
        if not _MONTH_RE.fullmatch(month):
            raise ValueError("month must use YYYY-MM format")
        selected = [dict(item) for item in snapshots if _snapshot_month(item) == month]
        timestamp = _timestamp_ms(generated_at_ms)
        rows: list[dict[str, Any]] = []
        source_ids: list[str] = []
        for item in selected:
            source_ids.append(_required_text(item.get("snapshot_id"), "snapshot_id", maximum_length=128))
            metrics = item.get("metrics") if isinstance(item.get("metrics"), Mapping) else {}
            rows.append(
                {
                    "net_pnl_usdt": _required_finite(metrics.get("net_pnl_usdt", 0.0), "net_pnl_usdt"),
                    "fees_usdt": _required_finite(metrics.get("fees_usdt", 0.0), "fees_usdt"),
                    "matched_fill_count": _required_non_negative_int(metrics.get("matched_fill_count", 0), "matched_fill_count"),
                    "maximum_drawdown_bps": _required_finite(metrics.get("maximum_drawdown_bps", 0.0), "maximum_drawdown_bps"),
                }
            )
        if any(row["fees_usdt"] < 0 or row["maximum_drawdown_bps"] < 0 for row in rows):
            raise ValueError("monthly report contains invalid negative risk metrics")
        net = sum(row["net_pnl_usdt"] for row in rows)
        fees = sum(row["fees_usdt"] for row in rows)
        fills = sum(row["matched_fill_count"] for row in rows)
        max_dd = max((row["maximum_drawdown_bps"] for row in rows), default=0.0)
        aggregate = {
            "month": month,
            "source_snapshot_ids": sorted(source_ids),
            "snapshot_count": len(rows),
            "net_pnl_usdt": round(net, 12),
            "fees_usdt": round(fees, 12),
            "matched_fill_count": fills,
            "maximum_drawdown_bps": round(max_dd, 6),
            "drawdown_alert": max_dd > self.policy.maximum_drawdown_bps,
        }
        evidence_hash = hashlib.sha256(_canonical_json(aggregate)).hexdigest()
        report_id = "p10m_" + evidence_hash[:32]
        report = {
            "schema_version": 2,
            "report_id": report_id,
            "generated_at_ms": timestamp,
            **aggregate,
            "evidence_sha256": evidence_hash,
            "mainnet_enabled": False,
        }
        existing = self.database.get_json(_MONTHLY_NS, report_id)
        if existing:
            canonical_existing = dict(existing["value"])
            canonical_existing["generated_at_ms"] = timestamp
            canonical_report = dict(report)
            canonical_report["generated_at_ms"] = timestamp
            if canonical_existing != canonical_report:
                raise VersionConflict("monthly report identity collision")
            return dict(existing["value"])
        self.database.put_json(_MONTHLY_NS, report_id, report, expected_version=0)
        self.database.append_event(
            _MONTHLY_NS,
            "monthly_performance_report",
            report_id,
            report,
            created_at_ms=timestamp,
        )
        return report

    def list_activations(self, limit: int = 100) -> list[dict[str, Any]]:
        return [dict(row["value"]) for row in list_json_items(self.database, _ACTIVATIONS_NS, limit=limit, newest_first=True)]

    def active_activations(self, *, now_ms: int | None = None, limit: int = 500) -> list[dict[str, Any]]:
        timestamp = _timestamp_ms(now_ms)
        return [
            item
            for item in self.list_activations(limit)
            if item.get("status") == "active"
            and (_optional_int(item.get("expires_at_ms")) or 0) > timestamp
            and _integrity_valid(item)
        ]

    def list_snapshots(self, limit: int = 500) -> list[dict[str, Any]]:
        return [dict(row["value"]) for row in list_json_items(self.database, _SNAPSHOTS_NS, limit=limit, newest_first=True)]

    def list_monthly_reports(self, limit: int = 36) -> list[dict[str, Any]]:
        return [dict(row["value"]) for row in list_json_items(self.database, _MONTHLY_NS, limit=limit, newest_first=True)]


def _authority_material(activation: Mapping[str, Any]) -> dict[str, Any]:
    keys = (
        "schema_version",
        "plan_id",
        "campaign_ids",
        "scope",
        "actor",
        "created_at_ms",
        "expires_at_ms",
        "previous_notional_usdt",
        "authorized_notional_usdt",
        "execution_environment",
        "single_canonical_execution_path",
        "kill_switch_override",
        "mainnet_enabled",
    )
    return {key: activation.get(key) for key in keys}


def _authority_hash(activation: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical_json(_authority_material(activation))).hexdigest()


def _integrity_valid(activation: Mapping[str, Any]) -> bool:
    supplied = str(activation.get("authority_hash") or "")
    return len(supplied) == 64 and supplied == _authority_hash(activation)


def _canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def _required_text(value: Any, name: str, *, maximum_length: int) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{name} is required")
    if len(text) > maximum_length:
        raise ValueError(f"{name} is too long")
    return text


def _required_finite(value: Any, name: str) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be finite") from exc
    if not math.isfinite(parsed):
        raise ValueError(f"{name} must be finite")
    return parsed


def _optional_finite(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _required_non_negative_int(value: Any, name: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a non-negative integer")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a non-negative integer") from exc
    if parsed < 0 or str(value).strip() not in {str(parsed), f"{parsed}.0"} and not isinstance(value, int):
        raise ValueError(f"{name} must be a non-negative integer")
    return parsed


def _optional_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _timestamp_ms(value: int | None) -> int:
    timestamp = int(time.time() * 1000) if value is None else int(value)
    if timestamp < 0:
        raise ValueError("timestamp must be non-negative")
    return timestamp


def _snapshot_month(snapshot: Mapping[str, Any]) -> str:
    timestamp = _optional_int(snapshot.get("captured_at_ms"))
    if timestamp is None or timestamp < 0:
        raise ValueError("snapshot captured_at_ms is required")
    return datetime.fromtimestamp(timestamp / 1000, tz=timezone.utc).strftime("%Y-%m")


__all__ = ["ControlledScalingService", "ScalingExecutionPolicy"]
