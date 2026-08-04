"""Canonical shared database for all SharipovAI chats, AI organs and evidence.

Production uses PostgreSQL through ``DATABASE_URL``. Local development and tests
use a single SQLite file unless ``SHARIPOVAI_DATABASE_REQUIRED=1`` is set.
Existing JSON files may remain as caches/backups, but this database is the source
of truth for cross-chat memory and system state.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

_TRUE = {"1", "true", "yes", "on"}
_SCHEMA_VERSION = 2
_SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")

_BASE_SCHEMA_STATEMENTS: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS project_kv (
        namespace TEXT NOT NULL,
        item_key TEXT NOT NULL,
        value_json TEXT NOT NULL,
        version INTEGER NOT NULL,
        updated_at_ms BIGINT NOT NULL,
        PRIMARY KEY (namespace, item_key)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS project_events (
        event_id TEXT PRIMARY KEY,
        namespace TEXT NOT NULL,
        entity_type TEXT NOT NULL,
        entity_id TEXT NOT NULL,
        payload_json TEXT NOT NULL,
        created_at_ms BIGINT NOT NULL
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS project_events_lookup_idx
    ON project_events(namespace, entity_type, entity_id, created_at_ms)
    """,
    """
    CREATE TABLE IF NOT EXISTS project_messages (
        project_id TEXT NOT NULL,
        chat_id TEXT NOT NULL,
        message_id TEXT PRIMARY KEY,
        role TEXT NOT NULL,
        content TEXT NOT NULL,
        metadata_json TEXT NOT NULL,
        created_at_ms BIGINT NOT NULL
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS project_messages_chat_idx
    ON project_messages(project_id, chat_id, created_at_ms)
    """,
    """
    CREATE TABLE IF NOT EXISTS ai_organ_state (
        organ_id TEXT PRIMARY KEY,
        state_json TEXT NOT NULL,
        version INTEGER NOT NULL,
        updated_at_ms BIGINT NOT NULL
    )
    """,
)

_AGENT_LEARNING_SCHEMA_STATEMENTS: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS agent_fixes (
        fix_id TEXT PRIMARY KEY,
        error_signature TEXT NOT NULL,
        failure_class TEXT,
        patch TEXT NOT NULL,
        patch_sha256 TEXT NOT NULL,
        success INTEGER NOT NULL CHECK (success IN (0, 1)),
        source TEXT NOT NULL,
        base_sha TEXT,
        applied_sha TEXT,
        attempt_count INTEGER NOT NULL DEFAULT 1 CHECK (attempt_count > 0),
        test_evidence_json TEXT NOT NULL,
        metadata_json TEXT NOT NULL,
        created_at_ms BIGINT NOT NULL,
        updated_at_ms BIGINT NOT NULL
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS agent_fixes_signature_idx
    ON agent_fixes(error_signature, success, created_at_ms)
    """,
    """
    CREATE INDEX IF NOT EXISTS agent_fixes_patch_idx
    ON agent_fixes(patch_sha256, created_at_ms)
    """,
    """
    CREATE TABLE IF NOT EXISTS agent_decisions (
        decision_id TEXT PRIMARY KEY,
        fix_id TEXT,
        kind TEXT NOT NULL,
        status TEXT NOT NULL,
        base_sha TEXT NOT NULL,
        target_branch TEXT NOT NULL,
        patch_sha256 TEXT NOT NULL,
        security_verdict TEXT NOT NULL,
        actor TEXT NOT NULL,
        rationale TEXT NOT NULL,
        metadata_json TEXT NOT NULL,
        created_at_ms BIGINT NOT NULL,
        updated_at_ms BIGINT NOT NULL,
        FOREIGN KEY (fix_id) REFERENCES agent_fixes(fix_id) ON DELETE SET NULL
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS agent_decisions_fix_idx
    ON agent_decisions(fix_id, created_at_ms)
    """,
    """
    CREATE INDEX IF NOT EXISTS agent_decisions_status_idx
    ON agent_decisions(status, kind, created_at_ms)
    """,
    """
    CREATE TABLE IF NOT EXISTS agent_decision_events (
        event_id TEXT PRIMARY KEY,
        decision_id TEXT NOT NULL,
        event_type TEXT NOT NULL,
        actor TEXT NOT NULL,
        payload_json TEXT NOT NULL,
        created_at_ms BIGINT NOT NULL,
        FOREIGN KEY (decision_id) REFERENCES agent_decisions(decision_id) ON DELETE CASCADE
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS agent_decision_events_lookup_idx
    ON agent_decision_events(decision_id, created_at_ms, event_id)
    """,
)

_MIGRATIONS: tuple[tuple[int, tuple[str, ...]], ...] = (
    (1, _BASE_SCHEMA_STATEMENTS),
    (2, _AGENT_LEARNING_SCHEMA_STATEMENTS),
)


class DatabaseUnavailable(RuntimeError):
    """Raised when the canonical project database is required but unavailable."""


class VersionConflict(RuntimeError):
    """Raised when an optimistic write uses an outdated version."""


class ProjectDatabase:
    """Small synchronous repository shared by every SharipovAI component."""

    def __init__(self, dsn: str | None = None) -> None:
        configured = (dsn if dsn is not None else os.getenv("DATABASE_URL", "")).strip()
        self.required = _truthy("SHARIPOVAI_DATABASE_REQUIRED", default=False)
        if not configured:
            if self.required:
                raise DatabaseUnavailable("DATABASE_URL is required but not configured")
            data_dir = Path(os.getenv("SHARIPOVAI_DATA_DIR", "data"))
            configured = f"sqlite:///{data_dir / 'sharipovai_shared.db'}"
        self.dsn = configured
        self.backend = "sqlite" if configured.startswith("sqlite:///") else "postgresql"

    @contextmanager
    def connect(self) -> Iterator[Any]:
        if self.backend == "sqlite":
            path = Path(self.dsn.removeprefix("sqlite:///"))
            path.parent.mkdir(parents=True, exist_ok=True)
            connection = sqlite3.connect(path, timeout=10, isolation_level=None)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("PRAGMA busy_timeout=10000")
        else:
            try:
                import psycopg  # type: ignore
            except ImportError as exc:  # pragma: no cover - production dependency
                raise DatabaseUnavailable("psycopg is required for PostgreSQL") from exc
            try:
                connection = psycopg.connect(self.dsn, autocommit=False)
            except Exception as exc:  # pragma: no cover - external service
                raise DatabaseUnavailable(f"PostgreSQL connection failed: {type(exc).__name__}: {exc}") from exc
        try:
            yield connection
        finally:
            connection.close()

    def initialize(self) -> None:
        """Apply every missing schema migration atomically and in version order."""

        with self.connect() as connection:
            try:
                self._begin(connection, immediate=True)
                self._execute(
                    connection,
                    """
                    CREATE TABLE IF NOT EXISTS schema_migrations (
                        version INTEGER PRIMARY KEY,
                        applied_at_ms BIGINT NOT NULL
                    )
                    """,
                )
                rows = self._fetchall(connection, "SELECT version FROM schema_migrations ORDER BY version")
                applied = {int(row["version"]) for row in rows}
                unsupported = sorted(version for version in applied if version > _SCHEMA_VERSION)
                if unsupported:
                    raise DatabaseUnavailable(
                        f"database schema is newer than this build: unsupported versions {unsupported}"
                    )
                for version, statements in _MIGRATIONS:
                    if version in applied:
                        continue
                    for statement in statements:
                        self._execute(connection, statement)
                    self._execute(
                        connection,
                        "INSERT INTO schema_migrations(version, applied_at_ms) VALUES (?, ?)",
                        (version, _now_ms()),
                    )
                connection.commit()
            except Exception:
                connection.rollback()
                raise

    def health(self) -> dict[str, Any]:
        try:
            self.initialize()
            with self.connect() as connection:
                row = self._fetchone(connection, "SELECT MAX(version) AS version FROM schema_migrations")
            return {
                "status": "ok",
                "backend": self.backend,
                "required": self.required,
                "schema_version": int((row or {}).get("version") or 0),
            }
        except Exception as exc:
            return {
                "status": "error",
                "backend": self.backend,
                "required": self.required,
                "error": f"{type(exc).__name__}: {exc}",
            }

    def put_json(
        self,
        namespace: str,
        key: str,
        value: Any,
        *,
        expected_version: int | None = None,
    ) -> int:
        namespace = _identifier(namespace, "namespace")
        key = _identifier(key, "key")
        payload = _json(value)
        now = _now_ms()
        with self.connect() as connection:
            try:
                self._begin(connection, immediate=True)
                row = self._fetchone(
                    connection,
                    "SELECT version FROM project_kv WHERE namespace = ? AND item_key = ?",
                    (namespace, key),
                    lock=True,
                )
                current = int(row["version"]) if row else 0
                if expected_version is not None and expected_version != current:
                    raise VersionConflict(
                        f"version mismatch for {namespace}/{key}: expected {expected_version}, current {current}"
                    )
                new_version = current + 1
                self._execute(
                    connection,
                    """
                    INSERT INTO project_kv(namespace, item_key, value_json, version, updated_at_ms)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(namespace, item_key) DO UPDATE SET
                        value_json = excluded.value_json,
                        version = excluded.version,
                        updated_at_ms = excluded.updated_at_ms
                    """,
                    (namespace, key, payload, new_version, now),
                )
                connection.commit()
                return new_version
            except Exception:
                connection.rollback()
                raise

    def get_json(self, namespace: str, key: str) -> dict[str, Any] | None:
        namespace = _identifier(namespace, "namespace")
        key = _identifier(key, "key")
        with self.connect() as connection:
            row = self._fetchone(
                connection,
                "SELECT value_json, version, updated_at_ms FROM project_kv WHERE namespace = ? AND item_key = ?",
                (namespace, key),
            )
        if not row:
            return None
        return {
            "value": json.loads(row["value_json"]),
            "version": int(row["version"]),
            "updated_at_ms": int(row["updated_at_ms"]),
        }

    def append_event(
        self,
        namespace: str,
        entity_type: str,
        entity_id: str,
        payload: Any,
        *,
        event_id: str | None = None,
        created_at_ms: int | None = None,
    ) -> str:
        namespace = _identifier(namespace, "namespace")
        entity_type = _identifier(entity_type, "entity_type")
        entity_id = _identifier(entity_id, "entity_id")
        event_id = _identifier(event_id or str(uuid.uuid4()), "event_id")
        timestamp = _timestamp(created_at_ms)
        with self.connect() as connection:
            try:
                self._begin(connection)
                self._execute(
                    connection,
                    """
                    INSERT INTO project_events(event_id, namespace, entity_type, entity_id, payload_json, created_at_ms)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (event_id, namespace, entity_type, entity_id, _json(payload), timestamp),
                )
                connection.commit()
            except Exception:
                connection.rollback()
                raise
        return event_id

    def list_events(
        self,
        namespace: str,
        *,
        entity_type: str | None = None,
        entity_id: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        namespace = _identifier(namespace, "namespace")
        limit = min(max(int(limit), 1), 1000)
        clauses = ["namespace = ?"]
        params: list[Any] = [namespace]
        if entity_type is not None:
            clauses.append("entity_type = ?")
            params.append(_identifier(entity_type, "entity_type"))
        if entity_id is not None:
            clauses.append("entity_id = ?")
            params.append(_identifier(entity_id, "entity_id"))
        params.append(limit)
        query = (
            "SELECT event_id, namespace, entity_type, entity_id, payload_json, created_at_ms "
            f"FROM project_events WHERE {' AND '.join(clauses)} "
            "ORDER BY created_at_ms DESC, event_id DESC LIMIT ?"
        )
        with self.connect() as connection:
            rows = self._fetchall(connection, query, tuple(params))
        return [
            {
                "event_id": row["event_id"],
                "namespace": row["namespace"],
                "entity_type": row["entity_type"],
                "entity_id": row["entity_id"],
                "payload": json.loads(row["payload_json"]),
                "created_at_ms": int(row["created_at_ms"]),
            }
            for row in rows
        ]

    def append_message(
        self,
        *,
        project_id: str,
        chat_id: str,
        message_id: str,
        role: str,
        content: str,
        metadata: Any | None = None,
        created_at_ms: int | None = None,
    ) -> None:
        project_id = _identifier(project_id, "project_id")
        chat_id = _identifier(chat_id, "chat_id")
        message_id = _identifier(message_id, "message_id")
        role = _role(role)
        content = str(content)
        if not content.strip():
            raise ValueError("content must not be empty")
        with self.connect() as connection:
            try:
                self._begin(connection)
                self._execute(
                    connection,
                    """
                    INSERT INTO project_messages(
                        project_id, chat_id, message_id, role, content, metadata_json, created_at_ms
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(message_id) DO NOTHING
                    """,
                    (
                        project_id,
                        chat_id,
                        message_id,
                        role,
                        content,
                        _json(metadata or {}),
                        _timestamp(created_at_ms),
                    ),
                )
                connection.commit()
            except Exception:
                connection.rollback()
                raise

    def list_messages(self, *, project_id: str, chat_id: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
        project_id = _identifier(project_id, "project_id")
        limit = min(max(int(limit), 1), 2000)
        if chat_id is None:
            query = (
                "SELECT project_id, chat_id, message_id, role, content, metadata_json, created_at_ms "
                "FROM project_messages WHERE project_id = ? "
                "ORDER BY created_at_ms ASC, message_id ASC LIMIT ?"
            )
            params = (project_id, limit)
        else:
            query = (
                "SELECT project_id, chat_id, message_id, role, content, metadata_json, created_at_ms "
                "FROM project_messages WHERE project_id = ? AND chat_id = ? "
                "ORDER BY created_at_ms ASC, message_id ASC LIMIT ?"
            )
            params = (project_id, _identifier(chat_id, "chat_id"), limit)
        with self.connect() as connection:
            rows = self._fetchall(connection, query, params)
        return [
            {
                "project_id": row["project_id"],
                "chat_id": row["chat_id"],
                "message_id": row["message_id"],
                "role": row["role"],
                "content": row["content"],
                "metadata": json.loads(row["metadata_json"]),
                "created_at_ms": int(row["created_at_ms"]),
            }
            for row in rows
        ]

    def set_ai_state(self, organ_id: str, state: Any, *, expected_version: int | None = None) -> int:
        organ_id = _identifier(organ_id, "organ_id")
        now = _now_ms()
        with self.connect() as connection:
            try:
                self._begin(connection, immediate=True)
                row = self._fetchone(
                    connection,
                    "SELECT version FROM ai_organ_state WHERE organ_id = ?",
                    (organ_id,),
                    lock=True,
                )
                current = int(row["version"]) if row else 0
                if expected_version is not None and current != expected_version:
                    raise VersionConflict(
                        f"version mismatch for AI organ {organ_id}: expected {expected_version}, current {current}"
                    )
                version = current + 1
                self._execute(
                    connection,
                    """
                    INSERT INTO ai_organ_state(organ_id, state_json, version, updated_at_ms)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(organ_id) DO UPDATE SET
                        state_json = excluded.state_json,
                        version = excluded.version,
                        updated_at_ms = excluded.updated_at_ms
                    """,
                    (organ_id, _json(state), version, now),
                )
                connection.commit()
                return version
            except Exception:
                connection.rollback()
                raise

    def get_ai_state(self, organ_id: str) -> dict[str, Any] | None:
        organ_id = _identifier(organ_id, "organ_id")
        with self.connect() as connection:
            row = self._fetchone(
                connection,
                "SELECT state_json, version, updated_at_ms FROM ai_organ_state WHERE organ_id = ?",
                (organ_id,),
            )
        if not row:
            return None
        return {
            "organ_id": organ_id,
            "state": json.loads(row["state_json"]),
            "version": int(row["version"]),
            "updated_at_ms": int(row["updated_at_ms"]),
        }

    def record_agent_fix(
        self,
        *,
        error_signature: str,
        patch: str,
        success: bool,
        source: str,
        fix_id: str | None = None,
        failure_class: str | None = None,
        base_sha: str | None = None,
        applied_sha: str | None = None,
        attempt_count: int = 1,
        test_evidence: Any | None = None,
        metadata: Any | None = None,
        created_at_ms: int | None = None,
    ) -> str:
        """Persist one immutable repair attempt for future repair-memory retrieval."""

        fix_id = _identifier(fix_id or str(uuid.uuid4()), "fix_id")
        error_signature = _nonempty_text(error_signature, "error_signature")
        patch = _nonempty_text(patch, "patch")
        source = _identifier(source, "source")
        failure_class = _optional_text(failure_class, "failure_class")
        base_sha = _optional_sha(base_sha, "base_sha")
        applied_sha = _optional_sha(applied_sha, "applied_sha")
        attempts = int(attempt_count)
        if attempts <= 0:
            raise ValueError("attempt_count must be positive")
        timestamp = _timestamp(created_at_ms)
        patch_sha256 = hashlib.sha256(patch.encode("utf-8")).hexdigest()
        with self.connect() as connection:
            try:
                self._begin(connection)
                self._execute(
                    connection,
                    """
                    INSERT INTO agent_fixes(
                        fix_id, error_signature, failure_class, patch, patch_sha256,
                        success, source, base_sha, applied_sha, attempt_count,
                        test_evidence_json, metadata_json, created_at_ms, updated_at_ms
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        fix_id,
                        error_signature,
                        failure_class,
                        patch,
                        patch_sha256,
                        1 if success else 0,
                        source,
                        base_sha,
                        applied_sha,
                        attempts,
                        _json(test_evidence or {}),
                        _json(metadata or {}),
                        timestamp,
                        timestamp,
                    ),
                )
                connection.commit()
            except Exception:
                connection.rollback()
                raise
        return fix_id

    def get_agent_fix(self, fix_id: str) -> dict[str, Any] | None:
        fix_id = _identifier(fix_id, "fix_id")
        with self.connect() as connection:
            row = self._fetchone(
                connection,
                """
                SELECT fix_id, error_signature, failure_class, patch, patch_sha256,
                       success, source, base_sha, applied_sha, attempt_count,
                       test_evidence_json, metadata_json, created_at_ms, updated_at_ms
                FROM agent_fixes WHERE fix_id = ?
                """,
                (fix_id,),
            )
        if not row:
            return None
        return {
            "fix_id": row["fix_id"],
            "error_signature": row["error_signature"],
            "failure_class": row["failure_class"],
            "patch": row["patch"],
            "patch_sha256": row["patch_sha256"],
            "success": bool(row["success"]),
            "source": row["source"],
            "base_sha": row["base_sha"],
            "applied_sha": row["applied_sha"],
            "attempt_count": int(row["attempt_count"]),
            "test_evidence": json.loads(row["test_evidence_json"]),
            "metadata": json.loads(row["metadata_json"]),
            "created_at_ms": int(row["created_at_ms"]),
            "updated_at_ms": int(row["updated_at_ms"]),
        }

    def record_agent_decision(
        self,
        *,
        kind: str,
        status: str,
        base_sha: str,
        target_branch: str,
        patch_sha256: str,
        security_verdict: str,
        actor: str,
        rationale: str,
        decision_id: str | None = None,
        fix_id: str | None = None,
        metadata: Any | None = None,
        created_at_ms: int | None = None,
    ) -> str:
        decision_id = _identifier(decision_id or str(uuid.uuid4()), "decision_id")
        fix_id = _identifier(fix_id, "fix_id") if fix_id is not None else None
        kind = _identifier(kind, "kind")
        status = _identifier(status, "status")
        base_sha = _sha(base_sha, "base_sha")
        target_branch = _identifier(target_branch, "target_branch")
        patch_sha256 = _sha256(patch_sha256, "patch_sha256")
        security_verdict = _identifier(security_verdict, "security_verdict")
        actor = _identifier(actor, "actor")
        rationale = _nonempty_text(rationale, "rationale")
        timestamp = _timestamp(created_at_ms)
        with self.connect() as connection:
            try:
                self._begin(connection)
                self._execute(
                    connection,
                    """
                    INSERT INTO agent_decisions(
                        decision_id, fix_id, kind, status, base_sha, target_branch,
                        patch_sha256, security_verdict, actor, rationale,
                        metadata_json, created_at_ms, updated_at_ms
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        decision_id,
                        fix_id,
                        kind,
                        status,
                        base_sha,
                        target_branch,
                        patch_sha256,
                        security_verdict,
                        actor,
                        rationale,
                        _json(metadata or {}),
                        timestamp,
                        timestamp,
                    ),
                )
                connection.commit()
            except Exception:
                connection.rollback()
                raise
        return decision_id

    def get_agent_decision(self, decision_id: str) -> dict[str, Any] | None:
        decision_id = _identifier(decision_id, "decision_id")
        with self.connect() as connection:
            row = self._fetchone(
                connection,
                """
                SELECT decision_id, fix_id, kind, status, base_sha, target_branch,
                       patch_sha256, security_verdict, actor, rationale,
                       metadata_json, created_at_ms, updated_at_ms
                FROM agent_decisions WHERE decision_id = ?
                """,
                (decision_id,),
            )
        if not row:
            return None
        return {
            "decision_id": row["decision_id"],
            "fix_id": row["fix_id"],
            "kind": row["kind"],
            "status": row["status"],
            "base_sha": row["base_sha"],
            "target_branch": row["target_branch"],
            "patch_sha256": row["patch_sha256"],
            "security_verdict": row["security_verdict"],
            "actor": row["actor"],
            "rationale": row["rationale"],
            "metadata": json.loads(row["metadata_json"]),
            "created_at_ms": int(row["created_at_ms"]),
            "updated_at_ms": int(row["updated_at_ms"]),
        }

    def append_agent_decision_event(
        self,
        *,
        decision_id: str,
        event_type: str,
        actor: str,
        payload: Any,
        event_id: str | None = None,
        created_at_ms: int | None = None,
    ) -> str:
        event_id = _identifier(event_id or str(uuid.uuid4()), "event_id")
        decision_id = _identifier(decision_id, "decision_id")
        event_type = _identifier(event_type, "event_type")
        actor = _identifier(actor, "actor")
        timestamp = _timestamp(created_at_ms)
        with self.connect() as connection:
            try:
                self._begin(connection)
                self._execute(
                    connection,
                    """
                    INSERT INTO agent_decision_events(
                        event_id, decision_id, event_type, actor, payload_json, created_at_ms
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (event_id, decision_id, event_type, actor, _json(payload), timestamp),
                )
                connection.commit()
            except Exception:
                connection.rollback()
                raise
        return event_id

    def list_agent_decision_events(self, decision_id: str, *, limit: int = 200) -> list[dict[str, Any]]:
        decision_id = _identifier(decision_id, "decision_id")
        limit = min(max(int(limit), 1), 2000)
        with self.connect() as connection:
            rows = self._fetchall(
                connection,
                """
                SELECT event_id, decision_id, event_type, actor, payload_json, created_at_ms
                FROM agent_decision_events
                WHERE decision_id = ?
                ORDER BY created_at_ms ASC, event_id ASC
                LIMIT ?
                """,
                (decision_id, limit),
            )
        return [
            {
                "event_id": row["event_id"],
                "decision_id": row["decision_id"],
                "event_type": row["event_type"],
                "actor": row["actor"],
                "payload": json.loads(row["payload_json"]),
                "created_at_ms": int(row["created_at_ms"]),
            }
            for row in rows
        ]

    def _begin(self, connection: Any, *, immediate: bool = False) -> None:
        if self.backend == "sqlite":
            connection.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")

    def _sql(self, query: str, *, lock: bool = False) -> str:
        normalized = " ".join(line.strip() for line in query.strip().splitlines())
        if self.backend == "postgresql":
            normalized = normalized.replace("?", "%s")
            if lock and normalized.upper().startswith("SELECT"):
                normalized += " FOR UPDATE"
        return normalized

    def _execute(self, connection: Any, query: str, params: tuple[Any, ...] = ()) -> Any:
        if self.backend == "sqlite":
            return connection.execute(self._sql(query), params)
        cursor = connection.cursor()
        cursor.execute(self._sql(query), params)
        return cursor

    def _fetchone(
        self,
        connection: Any,
        query: str,
        params: tuple[Any, ...] = (),
        *,
        lock: bool = False,
    ) -> dict[str, Any] | None:
        cursor = self._execute(connection, self._sql(query, lock=lock), params)
        row = cursor.fetchone()
        if row is None:
            return None
        if isinstance(row, sqlite3.Row):
            return dict(row)
        columns = [item.name if hasattr(item, "name") else item[0] for item in cursor.description]
        return dict(zip(columns, row, strict=True))

    def _fetchall(self, connection: Any, query: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        cursor = self._execute(connection, query, params)
        rows = cursor.fetchall()
        if not rows:
            return []
        if isinstance(rows[0], sqlite3.Row):
            return [dict(row) for row in rows]
        columns = [item.name if hasattr(item, "name") else item[0] for item in cursor.description]
        return [dict(zip(columns, row, strict=True)) for row in rows]


def _truthy(name: str, *, default: bool) -> bool:
    raw = os.getenv(name, "1" if default else "0")
    return raw.strip().lower() in _TRUE


def _now_ms() -> int:
    return int(time.time() * 1000)


def _timestamp(value: int | None) -> int:
    parsed = _now_ms() if value is None else int(value)
    if parsed <= 0:
        raise ValueError("timestamp must be positive")
    return parsed


def _identifier(value: str, name: str) -> str:
    clean = str(value).strip()
    if not clean or len(clean) > 200:
        raise ValueError(f"{name} must contain 1..200 characters")
    return clean


def _nonempty_text(value: str, name: str) -> str:
    clean = str(value)
    if not clean.strip():
        raise ValueError(f"{name} must not be empty")
    if "\x00" in clean:
        raise ValueError(f"{name} must not contain NUL bytes")
    return clean


def _optional_text(value: str | None, name: str) -> str | None:
    if value is None:
        return None
    return _nonempty_text(value, name)


def _sha(value: str, name: str) -> str:
    clean = str(value).strip().lower()
    if not _SHA_PATTERN.fullmatch(clean):
        raise ValueError(f"{name} must be a 40-character lowercase Git SHA")
    return clean


def _optional_sha(value: str | None, name: str) -> str | None:
    return None if value is None else _sha(value, name)


def _sha256(value: str, name: str) -> str:
    clean = str(value).strip().lower()
    if not _SHA256_PATTERN.fullmatch(clean):
        raise ValueError(f"{name} must be a 64-character lowercase SHA-256")
    return clean


def _role(value: str) -> str:
    clean = str(value).strip().lower()
    if clean not in {"system", "user", "assistant", "tool"}:
        raise ValueError("role must be system, user, assistant or tool")
    return clean


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True, allow_nan=False)
