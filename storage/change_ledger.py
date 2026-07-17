"""Evidence-backed change ledger for SharipovAI repository and runtime changes.

The ledger adapts the useful ECC install-state and decision-ledger concepts to the
existing :class:`ProjectDatabase`.  It never creates a second database and never
mutates files.  File operations are recorded as intent/evidence so future doctor,
repair, rollback and deployment code can act only on explicitly managed paths.
"""
from __future__ import annotations

import time
from pathlib import PurePosixPath
from typing import Any, Mapping, Sequence

from .project_database import ProjectDatabase, VersionConflict

_CHANGE_NAMESPACE = "project_change_ledger"
_CHANGE_ENTITY_TYPE = "change"
_ALLOWED_STATUSES = {"planned", "applied", "verified", "failed", "rolled_back"}
_ALLOWED_OPERATION_KINDS = {"create", "update", "delete", "move", "configuration"}
_ALLOWED_OWNERSHIP = {"managed", "shared"}
_TRANSITIONS = {
    "planned": {"applied", "failed", "rolled_back"},
    "applied": {"verified", "failed", "rolled_back"},
    "verified": {"rolled_back"},
    "failed": {"planned", "rolled_back"},
    "rolled_back": set(),
}
_SENSITIVE_KEY_PARTS = ("secret", "token", "password", "private_key", "api_key", "credential")


class ProjectChangeLedger:
    """Store managed-change intent and verification evidence in ProjectDatabase."""

    def __init__(self, database: ProjectDatabase | None = None) -> None:
        self.database = database or ProjectDatabase()
        self.database.initialize()

    def create_change(
        self,
        *,
        change_id: str,
        summary: str,
        actor: str,
        operations: Sequence[Mapping[str, Any]],
        metadata: Mapping[str, Any] | None = None,
        created_at_ms: int | None = None,
    ) -> dict[str, Any]:
        """Create a planned change and reject duplicate identifiers."""

        change_id = _identifier(change_id, "change_id")
        summary = _required_text(summary, "summary", maximum=2000)
        actor = _identifier(actor, "actor")
        normalized_operations = [_normalize_operation(item) for item in operations]
        if not normalized_operations:
            raise ValueError("operations must contain at least one managed change")
        clean_metadata = dict(metadata or {})
        _assert_no_sensitive_keys(clean_metadata)
        timestamp = _timestamp(created_at_ms)
        payload = {
            "change_id": change_id,
            "summary": summary,
            "actor": actor,
            "status": "planned",
            "operations": normalized_operations,
            "metadata": clean_metadata,
            "verification": {},
            "created_at_ms": timestamp,
            "updated_at_ms": timestamp,
        }
        version = self.database.put_json(
            _CHANGE_NAMESPACE,
            change_id,
            payload,
            expected_version=0,
        )
        event_id = self.database.append_event(
            _CHANGE_NAMESPACE,
            _CHANGE_ENTITY_TYPE,
            change_id,
            {"action": "created", "status": "planned", "version": version, "actor": actor},
            created_at_ms=timestamp,
        )
        return {**payload, "version": version, "event_id": event_id}

    def set_status(
        self,
        change_id: str,
        status: str,
        *,
        actor: str,
        verification: Mapping[str, Any] | None = None,
        note: str = "",
        expected_version: int | None = None,
        updated_at_ms: int | None = None,
    ) -> dict[str, Any]:
        """Move a change through an explicit lifecycle using optimistic locking."""

        change_id = _identifier(change_id, "change_id")
        actor = _identifier(actor, "actor")
        status = str(status).strip().lower()
        if status not in _ALLOWED_STATUSES:
            raise ValueError(f"unsupported change status: {status}")
        current = self.database.get_json(_CHANGE_NAMESPACE, change_id)
        if current is None:
            raise KeyError(change_id)
        current_version = int(current["version"])
        if expected_version is not None and int(expected_version) != current_version:
            raise VersionConflict(
                f"version mismatch for change {change_id}: expected {expected_version}, current {current_version}"
            )
        payload = dict(current["value"])
        previous_status = str(payload.get("status", "planned"))
        if status != previous_status and status not in _TRANSITIONS.get(previous_status, set()):
            raise ValueError(f"invalid change transition: {previous_status} -> {status}")
        clean_verification = dict(verification or {})
        _assert_no_sensitive_keys(clean_verification)
        timestamp = _timestamp(updated_at_ms)
        payload["status"] = status
        payload["updated_at_ms"] = timestamp
        payload["last_actor"] = actor
        if clean_verification:
            payload["verification"] = clean_verification
        if note:
            payload["note"] = _required_text(note, "note", maximum=4000)
        version = self.database.put_json(
            _CHANGE_NAMESPACE,
            change_id,
            payload,
            expected_version=current_version,
        )
        event_payload = {
            "action": "status_changed",
            "from": previous_status,
            "to": status,
            "version": version,
            "actor": actor,
        }
        if note:
            event_payload["note"] = payload["note"]
        event_id = self.database.append_event(
            _CHANGE_NAMESPACE,
            _CHANGE_ENTITY_TYPE,
            change_id,
            event_payload,
            created_at_ms=timestamp,
        )
        return {**payload, "version": version, "event_id": event_id}

    def get_change(self, change_id: str) -> dict[str, Any] | None:
        """Return the latest state for one change."""

        current = self.database.get_json(_CHANGE_NAMESPACE, _identifier(change_id, "change_id"))
        if current is None:
            return None
        return {**dict(current["value"]), "version": int(current["version"])}

    def history(self, change_id: str | None = None, *, limit: int = 100) -> list[dict[str, Any]]:
        """Return append-only evidence events, newest first."""

        return self.database.list_events(
            _CHANGE_NAMESPACE,
            entity_type=_CHANGE_ENTITY_TYPE,
            entity_id=_identifier(change_id, "change_id") if change_id is not None else None,
            limit=limit,
        )


def _normalize_operation(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError("each operation must be a mapping")
    kind = str(value.get("kind", "")).strip().lower()
    if kind not in _ALLOWED_OPERATION_KINDS:
        raise ValueError(f"unsupported operation kind: {kind or '<empty>'}")
    ownership = str(value.get("ownership", "managed")).strip().lower()
    if ownership not in _ALLOWED_OWNERSHIP:
        raise ValueError(f"unsupported ownership: {ownership}")
    path = _safe_relative_path(value.get("path"))
    normalized: dict[str, Any] = {"kind": kind, "path": path, "ownership": ownership}
    for key in ("destination", "digest_before", "digest_after", "reason"):
        raw = value.get(key)
        if raw in (None, ""):
            continue
        if key == "destination":
            normalized[key] = _safe_relative_path(raw)
        else:
            normalized[key] = _required_text(raw, key, maximum=2000)
    return normalized


def _safe_relative_path(value: Any) -> str:
    raw = str(value or "").strip().replace("\\", "/")
    path = PurePosixPath(raw)
    if not raw or path.is_absolute() or ".." in path.parts or path.parts[0] in {"", "."}:
        raise ValueError(f"managed path must be repository-relative and traversal-free: {raw!r}")
    return path.as_posix()


def _assert_no_sensitive_keys(value: Any, *, trail: tuple[str, ...] = ()) -> None:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            clean_key = str(key).strip().lower()
            if any(part in clean_key for part in _SENSITIVE_KEY_PARTS):
                location = ".".join((*trail, str(key)))
                raise ValueError(f"sensitive metadata key is forbidden: {location}")
            _assert_no_sensitive_keys(nested, trail=(*trail, str(key)))
    elif isinstance(value, (list, tuple)):
        for index, nested in enumerate(value):
            _assert_no_sensitive_keys(nested, trail=(*trail, str(index)))


def _identifier(value: Any, name: str) -> str:
    clean = str(value or "").strip()
    if not clean or len(clean) > 200:
        raise ValueError(f"{name} must contain 1..200 characters")
    return clean


def _required_text(value: Any, name: str, *, maximum: int) -> str:
    clean = str(value or "").strip()
    if not clean or len(clean) > maximum:
        raise ValueError(f"{name} must contain 1..{maximum} characters")
    return clean


def _timestamp(value: int | None) -> int:
    parsed = int(time.time() * 1000) if value is None else int(value)
    if parsed <= 0:
        raise ValueError("timestamp must be positive")
    return parsed


__all__ = ["ProjectChangeLedger"]
