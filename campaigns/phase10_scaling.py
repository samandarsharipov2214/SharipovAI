"""Phase 10 controlled Testnet scaling and persistent performance tracking."""
from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from storage import ProjectDatabase, list_json_items

_ACTIVATIONS_NS = "phase10_scaling_activations"
_SNAPSHOTS_NS = "phase10_performance_snapshots"
_MONTHLY_NS = "phase10_monthly_reports"


@dataclass(frozen=True, slots=True)
class ScalingExecutionPolicy:
    maximum_notional_usdt: float = 50.0
    maximum_step_multiplier: float = 1.5
    activation_ttl_seconds: int = 86400
    minimum_approved_campaigns: int = 2
    maximum_drawdown_bps: float = 250.0


class ControlledScalingService:
    """Creates bounded, expiring Testnet scaling authority records.

    This service never places orders and never changes Mainnet state. Existing
    execution code may only consume an active record after validating its hash,
    expiry, scope and notional ceiling.
    """

    def __init__(self, database: ProjectDatabase | None = None, *, policy: ScalingExecutionPolicy | None = None) -> None:
        self.database = database or ProjectDatabase()
        self.database.initialize()
        self.policy = policy or ScalingExecutionPolicy()

    def activate(self, plan: Mapping[str, Any], *, actor: str, confirmation: str, scope: str = "BTCUSDT", now_ms: int | None = None) -> dict[str, Any]:
        actor = actor.strip()
        scope = scope.strip().upper()
        if confirmation != "I_APPROVE_CONTROLLED_TESTNET_NOTIONAL_SCALING":
            raise ValueError("exact scaling confirmation is required")
        if not actor or not scope:
            raise ValueError("actor and scope are required")
        if str(plan.get("status") or "") != "eligible_for_manual_scaling_review":
            raise ValueError("scaling plan is not eligible")
        if list(plan.get("failed_gates") or []):
            raise ValueError("scaling plan contains failed gates")
        campaign_ids = sorted({str(item) for item in plan.get("campaign_ids") or [] if str(item)})
        if len(campaign_ids) < self.policy.minimum_approved_campaigns:
            raise ValueError("insufficient approved campaigns")
        current = float(plan.get("current_notional_usdt") or 0.0)
        proposed = float(plan.get("proposed_next_notional_usdt") or 0.0)
        ceiling = min(self.policy.maximum_notional_usdt, current * self.policy.maximum_step_multiplier)
        if current <= 0 or proposed <= current or proposed > ceiling:
            raise ValueError("proposed notional violates controlled step policy")
        evidence = plan.get("evidence") if isinstance(plan.get("evidence"), Mapping) else {}
        if float(evidence.get("maximum_drawdown_bps") or 0.0) > self.policy.maximum_drawdown_bps:
            raise ValueError("drawdown exceeds activation policy")
        timestamp = int(time.time() * 1000) if now_ms is None else int(now_ms)
        expires_at_ms = timestamp + self.policy.activation_ttl_seconds * 1000
        material = f"{plan.get('plan_id')}:{scope}:{proposed:.12f}:{expires_at_ms}:{actor}"
        activation_id = "p10a_" + hashlib.sha256(material.encode()).hexdigest()[:32]
        activation = {
            "schema_version": 1,
            "activation_id": activation_id,
            "plan_id": str(plan.get("plan_id") or ""),
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
            "authority_hash": hashlib.sha256(material.encode()).hexdigest(),
        }
        self.database.put_json(_ACTIVATIONS_NS, activation_id, activation, expected_version=0)
        self.database.append_event(_ACTIVATIONS_NS, "scaling_activated", activation_id, activation, created_at_ms=timestamp)
        return activation

    def revoke(self, activation_id: str, *, actor: str, reason: str, now_ms: int | None = None) -> dict[str, Any]:
        row = self.database.get_json(_ACTIVATIONS_NS, activation_id)
        if row is None:
            raise ValueError("activation not found")
        actor, reason = actor.strip(), reason.strip()
        if not actor or not reason:
            raise ValueError("actor and reason are required")
        activation = dict(row["value"])
        timestamp = int(time.time() * 1000) if now_ms is None else int(now_ms)
        activation.update({"status": "revoked", "revoked_at_ms": timestamp, "revoked_by": actor, "revoke_reason": reason})
        self.database.put_json(_ACTIVATIONS_NS, activation_id, activation, expected_version=int(row["version"]))
        self.database.append_event(_ACTIVATIONS_NS, "scaling_revoked", activation_id, activation, created_at_ms=timestamp)
        return activation

    def validate_authority(self, activation_id: str, *, scope: str, requested_notional_usdt: float, now_ms: int | None = None) -> dict[str, Any]:
        row = self.database.get_json(_ACTIVATIONS_NS, activation_id)
        if row is None:
            return {"allowed": False, "reason": "activation_not_found"}
        activation = dict(row["value"])
        timestamp = int(time.time() * 1000) if now_ms is None else int(now_ms)
        checks = {
            "active": activation.get("status") == "active",
            "not_expired": timestamp < int(activation.get("expires_at_ms") or 0),
            "scope_matches": str(scope).upper() == str(activation.get("scope") or "").upper(),
            "within_notional": 0 < float(requested_notional_usdt) <= float(activation.get("authorized_notional_usdt") or 0.0),
            "testnet_only": activation.get("execution_environment") == "testnet",
            "mainnet_locked": activation.get("mainnet_enabled") is False,
        }
        failed = sorted(name for name, passed in checks.items() if not passed)
        return {"allowed": not failed, "failed_checks": failed, "activation": activation}

    def record_snapshot(self, metrics: Mapping[str, Any], *, captured_at_ms: int | None = None) -> dict[str, Any]:
        timestamp = int(time.time() * 1000) if captured_at_ms is None else int(captured_at_ms)
        snapshot_id = "p10p_" + hashlib.sha256(f"{timestamp}:{metrics.get('campaign_id','')}".encode()).hexdigest()[:32]
        payload = {"schema_version": 1, "snapshot_id": snapshot_id, "captured_at_ms": timestamp, "metrics": dict(metrics), "mainnet_enabled": False}
        self.database.put_json(_SNAPSHOTS_NS, snapshot_id, payload, expected_version=0)
        self.database.append_event(_SNAPSHOTS_NS, "performance_snapshot", snapshot_id, payload, created_at_ms=timestamp)
        return payload

    def monthly_report(self, snapshots: Sequence[Mapping[str, Any]], *, month: str, generated_at_ms: int | None = None) -> dict[str, Any]:
        rows = [dict(item.get("metrics") or item) for item in snapshots]
        timestamp = int(time.time() * 1000) if generated_at_ms is None else int(generated_at_ms)
        net = sum(float(item.get("net_pnl_usdt") or 0.0) for item in rows)
        fees = sum(float(item.get("fees_usdt") or 0.0) for item in rows)
        fills = sum(int(item.get("matched_fill_count") or 0) for item in rows)
        max_dd = max((float(item.get("maximum_drawdown_bps") or 0.0) for item in rows), default=0.0)
        report = {"schema_version": 1, "month": month, "generated_at_ms": timestamp, "snapshot_count": len(rows), "net_pnl_usdt": round(net, 12), "fees_usdt": round(fees, 12), "matched_fill_count": fills, "maximum_drawdown_bps": round(max_dd, 6), "drawdown_alert": max_dd > self.policy.maximum_drawdown_bps, "mainnet_enabled": False}
        self.database.put_json(_MONTHLY_NS, month, report, expected_version=int(self.database.get_json(_MONTHLY_NS, month)["version"]) if self.database.get_json(_MONTHLY_NS, month) else 0)
        self.database.append_event(_MONTHLY_NS, "monthly_performance_report", month, report, created_at_ms=timestamp)
        return report

    def list_activations(self, limit: int = 100) -> list[dict[str, Any]]:
        return [dict(row["value"]) for row in list_json_items(self.database, _ACTIVATIONS_NS, limit=limit, newest_first=True)]

    def list_snapshots(self, limit: int = 500) -> list[dict[str, Any]]:
        return [dict(row["value"]) for row in list_json_items(self.database, _SNAPSHOTS_NS, limit=limit, newest_first=True)]

    def list_monthly_reports(self, limit: int = 36) -> list[dict[str, Any]]:
        return [dict(row["value"]) for row in list_json_items(self.database, _MONTHLY_NS, limit=limit, newest_first=True)]


__all__ = ["ControlledScalingService", "ScalingExecutionPolicy"]
