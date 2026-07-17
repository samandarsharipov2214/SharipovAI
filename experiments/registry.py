"""Persistent, evidence-backed research experiment registry.

Every experiment is stored in the canonical :class:`ProjectDatabase`.  The
registry records immutable source identity (commit + data manifest + config),
append-only lifecycle events, normalized results and promotion decisions.  It
never changes runtime execution flags and never promotes a strategy by itself.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import asdict, dataclass, is_dataclass
from enum import Enum
from typing import Any, Mapping

from storage import ProjectDatabase, VersionConflict, list_json_items

_NAMESPACE = "research_experiments"
_EVENT_NAMESPACE = "research_experiment_events"
_COMMIT_RE = re.compile(r"^[0-9a-fA-F]{7,64}$")
_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")
_STATUSES = {
    "created",
    "running",
    "completed",
    "failed",
    "promotion_pending",
    "promoted",
    "rejected",
}
_TRANSITIONS = {
    "created": {"running", "completed", "failed"},
    "running": {"completed", "failed"},
    "completed": {"promotion_pending", "failed"},
    "promotion_pending": {"promoted", "rejected", "completed"},
    "rejected": {"promotion_pending"},
    "failed": {"running"},
    "promoted": set(),
}


@dataclass(frozen=True, slots=True)
class ExperimentIdentity:
    experiment_id: str
    commit_sha: str
    manifest_id: str
    manifest_sha256: str
    strategy_name: str


class ExperimentRegistry:
    """Canonical registry for backtest, paper and Testnet research evidence."""

    def __init__(self, database: ProjectDatabase | None = None) -> None:
        self.database = database or ProjectDatabase()
        self.database.initialize()

    def create(
        self,
        *,
        commit_sha: str,
        manifest: Mapping[str, Any],
        strategy_name: str,
        strategy_config: Mapping[str, Any],
        backtest_config: Mapping[str, Any],
        experiment_id: str | None = None,
        metadata: Mapping[str, Any] | None = None,
        created_at_ms: int | None = None,
    ) -> dict[str, Any]:
        timestamp = _timestamp(created_at_ms)
        clean_commit = _commit_sha(commit_sha)
        clean_manifest = _normalize_manifest(manifest)
        clean_strategy = _identifier(strategy_name, "strategy_name")
        clean_strategy_config = _jsonable(strategy_config)
        clean_backtest_config = _jsonable(backtest_config)
        clean_metadata = _jsonable(metadata or {})
        identity_payload = {
            "commit_sha": clean_commit,
            "manifest": clean_manifest,
            "strategy_name": clean_strategy,
            "strategy_config": clean_strategy_config,
            "backtest_config": clean_backtest_config,
            "created_at_ms": timestamp,
        }
        identifier = _identifier(
            experiment_id or _experiment_id(identity_payload),
            "experiment_id",
        )
        payload = {
            "experiment_id": identifier,
            "status": "created",
            "commit_sha": clean_commit,
            "manifest": clean_manifest,
            "strategy_name": clean_strategy,
            "strategy_config": clean_strategy_config,
            "backtest_config": clean_backtest_config,
            "metadata": clean_metadata,
            "results": {},
            "promotion": {
                "status": "not_evaluated",
                "target_stage": "",
                "report": {},
                "manual_decision": {},
            },
            "created_at_ms": timestamp,
            "updated_at_ms": timestamp,
        }
        version = self.database.put_json(
            _NAMESPACE,
            identifier,
            payload,
            expected_version=0,
        )
        event_id = self._event(
            identifier,
            "created",
            {
                "version": version,
                "commit_sha": clean_commit,
                "manifest_id": clean_manifest["manifest_id"],
                "strategy_name": clean_strategy,
            },
            timestamp,
        )
        return {**payload, "version": version, "event_id": event_id}

    def get(self, experiment_id: str) -> dict[str, Any] | None:
        current = self.database.get_json(
            _NAMESPACE,
            _identifier(experiment_id, "experiment_id"),
        )
        if current is None:
            return None
        return {
            **dict(current["value"]),
            "version": int(current["version"]),
            "database_updated_at_ms": int(current["updated_at_ms"]),
        }

    def list(self, *, limit: int = 200, newest_first: bool = True) -> list[dict[str, Any]]:
        rows = list_json_items(
            self.database,
            _NAMESPACE,
            limit=min(max(int(limit), 1), 2_000),
            newest_first=newest_first,
        )
        return [
            {
                **dict(row["value"]),
                "version": int(row["version"]),
                "database_updated_at_ms": int(row["updated_at_ms"]),
            }
            for row in rows
        ]

    def set_status(
        self,
        experiment_id: str,
        status: str,
        *,
        actor: str,
        note: str = "",
        expected_version: int | None = None,
        updated_at_ms: int | None = None,
    ) -> dict[str, Any]:
        clean_status = str(status).strip().lower()
        if clean_status not in _STATUSES:
            raise ValueError(f"unsupported experiment status: {clean_status}")
        return self._update(
            experiment_id,
            actor=actor,
            expected_version=expected_version,
            updated_at_ms=updated_at_ms,
            action="status_changed",
            mutate=lambda payload: _change_status(payload, clean_status, note),
        )

    def record_result(
        self,
        experiment_id: str,
        result_name: str,
        result: Any,
        *,
        actor: str,
        expected_version: int | None = None,
        updated_at_ms: int | None = None,
    ) -> dict[str, Any]:
        name = _identifier(result_name, "result_name")
        normalized = _jsonable(result)

        def mutate(payload: dict[str, Any]) -> dict[str, Any]:
            if str(payload.get("status")) in {"promoted"}:
                raise ValueError("promoted experiment results are immutable")
            results = dict(payload.get("results") or {})
            results[name] = normalized
            payload["results"] = results
            if payload.get("status") == "created":
                payload["status"] = "running"
            return payload

        return self._update(
            experiment_id,
            actor=actor,
            expected_version=expected_version,
            updated_at_ms=updated_at_ms,
            action="result_recorded",
            event_details={"result_name": name},
            mutate=mutate,
        )

    def complete(
        self,
        experiment_id: str,
        *,
        actor: str,
        expected_version: int | None = None,
        updated_at_ms: int | None = None,
    ) -> dict[str, Any]:
        def mutate(payload: dict[str, Any]) -> dict[str, Any]:
            results = payload.get("results")
            if not isinstance(results, Mapping) or not results:
                raise ValueError("experiment cannot complete without results")
            return _change_status(payload, "completed", "")

        return self._update(
            experiment_id,
            actor=actor,
            expected_version=expected_version,
            updated_at_ms=updated_at_ms,
            action="completed",
            mutate=mutate,
        )

    def save_promotion_report(
        self,
        experiment_id: str,
        report: Mapping[str, Any],
        *,
        actor: str,
        expected_version: int | None = None,
        updated_at_ms: int | None = None,
    ) -> dict[str, Any]:
        normalized = _jsonable(report)
        target = _identifier(normalized.get("target_stage"), "target_stage")

        def mutate(payload: dict[str, Any]) -> dict[str, Any]:
            if payload.get("status") not in {"completed", "rejected", "promotion_pending"}:
                raise ValueError("promotion report requires a completed experiment")
            payload["status"] = "promotion_pending" if normalized.get(
                "eligible_for_manual_approval"
            ) else "completed"
            payload["promotion"] = {
                "status": "awaiting_manual_approval"
                if normalized.get("eligible_for_manual_approval")
                else "blocked",
                "target_stage": target,
                "report": normalized,
                "manual_decision": {},
            }
            return payload

        return self._update(
            experiment_id,
            actor=actor,
            expected_version=expected_version,
            updated_at_ms=updated_at_ms,
            action="promotion_report_saved",
            event_details={"target_stage": target},
            mutate=mutate,
        )

    def manual_decision(
        self,
        experiment_id: str,
        *,
        target_stage: str,
        approve: bool,
        actor: str,
        reason: str,
        approval_token: str,
        expected_version: int | None = None,
        decided_at_ms: int | None = None,
    ) -> dict[str, Any]:
        identifier = _identifier(experiment_id, "experiment_id")
        target = _identifier(target_stage, "target_stage")
        clean_actor = _identifier(actor, "actor")
        clean_reason = _required_text(reason, "reason", 4_000)
        expected_token = f"APPROVE:{identifier}:{target}"
        if approve and approval_token != expected_token:
            raise ValueError("manual approval token does not match experiment and stage")

        def mutate(payload: dict[str, Any]) -> dict[str, Any]:
            promotion = dict(payload.get("promotion") or {})
            report = promotion.get("report")
            if not isinstance(report, Mapping):
                raise ValueError("promotion report is missing")
            if str(promotion.get("target_stage")) != target:
                raise ValueError("manual decision target does not match promotion report")
            if approve and not bool(report.get("eligible_for_manual_approval")):
                raise ValueError("blocked promotion cannot be manually approved")
            promotion["status"] = "approved" if approve else "rejected"
            promotion["manual_decision"] = {
                "approved": bool(approve),
                "actor": clean_actor,
                "reason": clean_reason,
                "decided_at_ms": _timestamp(decided_at_ms),
            }
            payload["promotion"] = promotion
            payload["status"] = "promoted" if approve else "rejected"
            return payload

        return self._update(
            identifier,
            actor=clean_actor,
            expected_version=expected_version,
            updated_at_ms=decided_at_ms,
            action="manual_promotion_approved" if approve else "manual_promotion_rejected",
            event_details={"target_stage": target, "reason": clean_reason},
            mutate=mutate,
        )

    def compare(self, experiment_ids: list[str] | tuple[str, ...]) -> dict[str, Any]:
        identifiers = [_identifier(value, "experiment_id") for value in experiment_ids]
        if len(identifiers) < 2:
            raise ValueError("comparison requires at least two experiment identifiers")
        if len(set(identifiers)) != len(identifiers):
            raise ValueError("comparison identifiers must be unique")
        records = []
        for identifier in identifiers[:20]:
            record = self.get(identifier)
            if record is None:
                raise KeyError(identifier)
            records.append(record)
        rows = [_comparison_row(record) for record in records]
        ranked = sorted(
            rows,
            key=lambda item: (
                float(item.get("oos_net_pnl", 0.0)),
                -float(item.get("max_drawdown_percent", 0.0)),
                float(item.get("profitable_window_percent", 0.0)),
            ),
            reverse=True,
        )
        return {
            "status": "ok",
            "experiment_count": len(rows),
            "rows": rows,
            "ranking": [row["experiment_id"] for row in ranked],
        }

    def history(self, experiment_id: str, *, limit: int = 200) -> list[dict[str, Any]]:
        return self.database.list_events(
            _EVENT_NAMESPACE,
            entity_type="experiment",
            entity_id=_identifier(experiment_id, "experiment_id"),
            limit=limit,
        )

    def _update(
        self,
        experiment_id: str,
        *,
        actor: str,
        action: str,
        mutate: Any,
        expected_version: int | None,
        updated_at_ms: int | None,
        event_details: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        identifier = _identifier(experiment_id, "experiment_id")
        clean_actor = _identifier(actor, "actor")
        current = self.database.get_json(_NAMESPACE, identifier)
        if current is None:
            raise KeyError(identifier)
        version = int(current["version"])
        if expected_version is not None and int(expected_version) != version:
            raise VersionConflict(
                f"version mismatch for experiment {identifier}: "
                f"expected {expected_version}, current {version}"
            )
        before = dict(current["value"])
        payload = mutate(dict(before))
        timestamp = _timestamp(updated_at_ms)
        payload["updated_at_ms"] = timestamp
        payload["last_actor"] = clean_actor
        new_version = self.database.put_json(
            _NAMESPACE,
            identifier,
            _jsonable(payload),
            expected_version=version,
        )
        event_id = self._event(
            identifier,
            action,
            {
                "actor": clean_actor,
                "version": new_version,
                "status_before": before.get("status"),
                "status_after": payload.get("status"),
                **dict(event_details or {}),
            },
            timestamp,
        )
        return {**payload, "version": new_version, "event_id": event_id}

    def _event(
        self,
        experiment_id: str,
        action: str,
        details: Mapping[str, Any],
        timestamp: int,
    ) -> str:
        return self.database.append_event(
            _EVENT_NAMESPACE,
            "experiment",
            experiment_id,
            {"action": action, **_jsonable(details)},
            created_at_ms=timestamp,
        )


def _change_status(payload: dict[str, Any], status: str, note: str) -> dict[str, Any]:
    previous = str(payload.get("status", "created"))
    if status != previous and status not in _TRANSITIONS.get(previous, set()):
        raise ValueError(f"invalid experiment transition: {previous} -> {status}")
    payload["status"] = status
    if note:
        payload["status_note"] = _required_text(note, "note", 4_000)
    return payload


def _normalize_manifest(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError("manifest must be an object")
    normalized = _jsonable(value)
    manifest_id = normalized.get("manifest_id") or normalized.get("dataset_id")
    normalized["manifest_id"] = _identifier(manifest_id, "manifest_id")
    normalized["version"] = _identifier(normalized.get("version"), "manifest version")
    digest = str(normalized.get("sha256") or normalized.get("manifest_sha256") or "").strip().lower()
    if digest and not _SHA256_RE.fullmatch(digest):
        raise ValueError("manifest sha256 must contain 64 hexadecimal characters")
    normalized["sha256"] = digest
    normalized["validated"] = bool(normalized.get("validated", False))
    return normalized


def _comparison_row(record: Mapping[str, Any]) -> dict[str, Any]:
    results = record.get("results") if isinstance(record.get("results"), Mapping) else {}
    walk = results.get("walk_forward") if isinstance(results.get("walk_forward"), Mapping) else {}
    promotion = record.get("promotion") if isinstance(record.get("promotion"), Mapping) else {}
    return {
        "experiment_id": record.get("experiment_id"),
        "strategy_name": record.get("strategy_name"),
        "commit_sha": record.get("commit_sha"),
        "manifest_id": (record.get("manifest") or {}).get("manifest_id")
        if isinstance(record.get("manifest"), Mapping)
        else "",
        "status": record.get("status"),
        "oos_net_pnl": _number(walk.get("net_pnl")),
        "return_percent": _number(walk.get("return_percent")),
        "max_drawdown_percent": _number(walk.get("max_drawdown_percent")),
        "profitable_window_percent": _number(walk.get("profitable_window_percent")),
        "total_fees": _number(walk.get("total_fees")),
        "total_slippage_cost": _number(walk.get("total_slippage_cost")),
        "total_funding_cost": _number(walk.get("total_funding_cost")),
        "promotion_status": promotion.get("status"),
        "promotion_target": promotion.get("target_stage"),
    }


def _experiment_id(value: Mapping[str, Any]) -> str:
    digest = hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:20]
    return f"exp_{digest}"


def _jsonable(value: Any) -> Any:
    if is_dataclass(value):
        value = asdict(value)
    elif isinstance(value, Enum):
        value = value.value
    elif isinstance(value, Mapping):
        value = {str(key): _jsonable(item) for key, item in value.items()}
    elif isinstance(value, (list, tuple, set, frozenset)):
        value = [_jsonable(item) for item in value]
    payload = json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True)
    return json.loads(payload)


def _identifier(value: Any, name: str) -> str:
    clean = str(value or "").strip()
    if not clean or len(clean) > 200:
        raise ValueError(f"{name} must contain 1..200 characters")
    return clean


def _required_text(value: Any, name: str, maximum: int) -> str:
    clean = str(value or "").strip()
    if not clean or len(clean) > maximum:
        raise ValueError(f"{name} must contain 1..{maximum} characters")
    return clean


def _commit_sha(value: Any) -> str:
    clean = str(value or "").strip().lower()
    if not _COMMIT_RE.fullmatch(clean):
        raise ValueError("commit_sha must contain 7..64 hexadecimal characters")
    return clean


def _timestamp(value: int | None) -> int:
    parsed = int(time.time() * 1000) if value is None else int(value)
    if parsed <= 0:
        raise ValueError("timestamp must be positive")
    return parsed


def _number(value: Any) -> float:
    try:
        parsed = float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0
    return parsed if parsed == parsed and abs(parsed) != float("inf") else 0.0


__all__ = ["ExperimentIdentity", "ExperimentRegistry"]
