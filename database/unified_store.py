"""Fail-closed PostgreSQL access for shared SharipovAI state.

This module intentionally exposes a small, synchronous API first. Existing JSON
stores can migrate one at a time without changing the canonical schema.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlsplit

import psycopg
from psycopg.rows import dict_row


class DatabaseConfigurationError(RuntimeError):
    """Raised when production database configuration is absent or unsafe."""


def validate_database_url(value: str | None) -> str:
    """Return a validated PostgreSQL URL without ever logging credentials."""
    url = (value or "").strip()
    if not url:
        raise DatabaseConfigurationError("DATABASE_URL is not configured")
    parsed = urlsplit(url)
    if parsed.scheme not in {"postgres", "postgresql"}:
        raise DatabaseConfigurationError("DATABASE_URL must use PostgreSQL")
    if not parsed.hostname or not parsed.path or parsed.path == "/":
        raise DatabaseConfigurationError("DATABASE_URL is incomplete")
    if parsed.fragment:
        raise DatabaseConfigurationError("DATABASE_URL fragments are forbidden")
    return url


@dataclass(frozen=True)
class DatabaseHealth:
    status: str
    schema_ready: bool


class UnifiedStore:
    """Canonical shared store used by chats and all nine AI organs."""

    def __init__(self, database_url: str | None = None) -> None:
        self._database_url = validate_database_url(
            database_url if database_url is not None else os.getenv("DATABASE_URL")
        )

    def _connect(self):
        return psycopg.connect(
            self._database_url,
            connect_timeout=5,
            row_factory=dict_row,
            application_name="SharipovAI",
        )

    def migrate(self, migration_path: str | Path | None = None) -> None:
        path = Path(migration_path or Path(__file__).with_name("migrations") / "0001_unified_core.sql")
        sql = path.read_text(encoding="utf-8")
        if "CREATE TABLE IF NOT EXISTS project_memory" not in sql:
            raise RuntimeError("Unified database migration contract is incomplete")
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(sql)
            connection.commit()

    def health(self) -> DatabaseHealth:
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
                    "WHERE table_schema='public' AND table_name='project_memory') AS ready"
                )
                row = cursor.fetchone()
        ready = bool(row and row.get("ready"))
        return DatabaseHealth(status="healthy" if ready else "blocked", schema_ready=ready)

    def put_memory(
        self,
        *,
        namespace: str,
        key: str,
        value: Mapping[str, Any],
        confidence: float = 100.0,
        project_key: str = "SharipovAI",
    ) -> None:
        namespace = _required_text(namespace, "namespace")
        key = _required_text(key, "key")
        project_key = _required_text(project_key, "project_key")
        if not 0 <= float(confidence) <= 100:
            raise ValueError("confidence must be between 0 and 100")
        payload = json.dumps(dict(value), ensure_ascii=False, separators=(",", ":"))
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO project_memory(project_key, namespace, memory_key, value, confidence)
                    VALUES (%s, %s, %s, %s::jsonb, %s)
                    ON CONFLICT (project_key, namespace, memory_key)
                    DO UPDATE SET value=EXCLUDED.value,
                                  confidence=EXCLUDED.confidence,
                                  updated_at=NOW()
                    """,
                    (project_key, namespace, key, payload, float(confidence)),
                )
            connection.commit()

    def get_memory(
        self,
        *,
        namespace: str,
        key: str,
        project_key: str = "SharipovAI",
    ) -> dict[str, Any] | None:
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT value, confidence, updated_at
                    FROM project_memory
                    WHERE project_key=%s AND namespace=%s AND memory_key=%s
                      AND (valid_until IS NULL OR valid_until > NOW())
                    """,
                    (
                        _required_text(project_key, "project_key"),
                        _required_text(namespace, "namespace"),
                        _required_text(key, "key"),
                    ),
                )
                row = cursor.fetchone()
        return dict(row) if row else None

    def set_ai_state(self, *, organ_key: str, status: str, state: Mapping[str, Any]) -> None:
        allowed = {"starting", "healthy", "degraded", "blocked", "offline"}
        if status not in allowed:
            raise ValueError(f"unsupported AI status: {status}")
        payload = json.dumps(dict(state), ensure_ascii=False, separators=(",", ":"))
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO ai_organ_state(organ_key, status, state, last_heartbeat_at)
                    VALUES (%s, %s, %s::jsonb, NOW())
                    ON CONFLICT (organ_key)
                    DO UPDATE SET status=EXCLUDED.status,
                                  state=EXCLUDED.state,
                                  last_heartbeat_at=NOW(),
                                  updated_at=NOW()
                    """,
                    (_required_text(organ_key, "organ_key"), status, payload),
                )
            connection.commit()

    def append_audit(
        self,
        *,
        event_type: str,
        severity: str,
        payload: Mapping[str, Any],
        actor: str | None = None,
        correlation_id: str | None = None,
    ) -> None:
        if severity not in {"info", "warning", "error", "critical"}:
            raise ValueError("unsupported audit severity")
        encoded = json.dumps(dict(payload), ensure_ascii=False, separators=(",", ":"))
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO audit_events(event_type, severity, actor, correlation_id, payload)
                    VALUES (%s, %s, %s, %s, %s::jsonb)
                    """,
                    (_required_text(event_type, "event_type"), severity, actor, correlation_id, encoded),
                )
            connection.commit()


def _required_text(value: str, field: str) -> str:
    normalized = str(value).strip()
    if not normalized:
        raise ValueError(f"{field} is required")
    if len(normalized) > 255:
        raise ValueError(f"{field} is too long")
    return normalized
