"""Versioned, reversible Memory Layer schema on the canonical ProjectDatabase."""
from __future__ import annotations

import time
from typing import Any

from storage import ProjectDatabase

MEMORY_SCHEMA_VERSION = 1

_SCHEMA_V1: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS memory_raw_logs (
        log_id TEXT PRIMARY KEY,
        team_id TEXT NOT NULL,
        user_id TEXT NOT NULL,
        agent_id TEXT NOT NULL,
        session_id TEXT NOT NULL,
        message_role TEXT NOT NULL,
        content TEXT NOT NULL,
        source_ref TEXT NOT NULL,
        source_digest TEXT NOT NULL UNIQUE,
        processing_status TEXT NOT NULL,
        metadata_json TEXT NOT NULL,
        created_at_ms BIGINT NOT NULL,
        processed_at_ms BIGINT
    )
    """,
    "CREATE INDEX IF NOT EXISTS memory_raw_lookup_idx ON memory_raw_logs(team_id, agent_id, user_id, session_id, created_at_ms)",
    "CREATE INDEX IF NOT EXISTS memory_raw_status_idx ON memory_raw_logs(processing_status, created_at_ms)",
    """
    CREATE TABLE IF NOT EXISTS memory_facts (
        fact_id TEXT PRIMARY KEY,
        team_id TEXT NOT NULL,
        user_id TEXT NOT NULL,
        agent_id TEXT NOT NULL,
        session_id TEXT NOT NULL,
        content TEXT NOT NULL,
        background TEXT NOT NULL,
        fact_type TEXT NOT NULL,
        status TEXT NOT NULL,
        priority INTEGER NOT NULL,
        source_log_id TEXT,
        source_ref TEXT NOT NULL,
        source_digest TEXT NOT NULL,
        embedding_json TEXT,
        metadata_json TEXT NOT NULL,
        created_at_ms BIGINT NOT NULL,
        updated_at_ms BIGINT NOT NULL,
        UNIQUE(team_id, agent_id, user_id, source_digest),
        FOREIGN KEY (source_log_id) REFERENCES memory_raw_logs(log_id) ON DELETE SET NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS memory_fact_lookup_idx ON memory_facts(team_id, agent_id, user_id, status, updated_at_ms)",
    "CREATE INDEX IF NOT EXISTS memory_fact_session_idx ON memory_facts(session_id, created_at_ms)",
    """
    CREATE TABLE IF NOT EXISTS memory_scenarios (
        scenario_id TEXT PRIMARY KEY,
        team_id TEXT NOT NULL,
        user_id TEXT NOT NULL,
        agent_id TEXT NOT NULL,
        name TEXT NOT NULL,
        summary TEXT NOT NULL,
        status TEXT NOT NULL,
        version INTEGER NOT NULL,
        metadata_json TEXT NOT NULL,
        created_at_ms BIGINT NOT NULL,
        updated_at_ms BIGINT NOT NULL,
        UNIQUE(team_id, agent_id, user_id, name, version)
    )
    """,
    "CREATE INDEX IF NOT EXISTS memory_scenario_lookup_idx ON memory_scenarios(team_id, agent_id, user_id, status, updated_at_ms)",
    """
    CREATE TABLE IF NOT EXISTS memory_core (
        core_id TEXT PRIMARY KEY,
        team_id TEXT NOT NULL,
        user_id TEXT NOT NULL,
        agent_id TEXT NOT NULL,
        content TEXT NOT NULL,
        status TEXT NOT NULL,
        version INTEGER NOT NULL,
        metadata_json TEXT NOT NULL,
        created_at_ms BIGINT NOT NULL,
        updated_at_ms BIGINT NOT NULL,
        UNIQUE(team_id, agent_id, user_id, version)
    )
    """,
    "CREATE INDEX IF NOT EXISTS memory_core_lookup_idx ON memory_core(team_id, agent_id, user_id, status, updated_at_ms)",
)


class MemoryMigrationManager:
    """Apply only Memory Layer tables without changing the core schema owner."""

    def __init__(self, database: ProjectDatabase | None = None) -> None:
        self.database = database or ProjectDatabase()
        self.fts_available = False

    def initialize(self) -> dict[str, Any]:
        self.database.initialize()
        with self.database.connect() as connection:
            try:
                self.database._begin(connection, immediate=True)
                self.database._execute(
                    connection,
                    """
                    CREATE TABLE IF NOT EXISTS memory_schema_migrations (
                        version INTEGER PRIMARY KEY,
                        applied_at_ms BIGINT NOT NULL
                    )
                    """,
                )
                rows = self.database._fetchall(
                    connection,
                    "SELECT version FROM memory_schema_migrations ORDER BY version",
                )
                applied = {int(row["version"]) for row in rows}
                unsupported = sorted(version for version in applied if version > MEMORY_SCHEMA_VERSION)
                if unsupported:
                    raise RuntimeError(f"memory schema is newer than this build: {unsupported}")
                if 1 not in applied:
                    for statement in _SCHEMA_V1:
                        self.database._execute(connection, statement)
                    self.database._execute(
                        connection,
                        "INSERT INTO memory_schema_migrations(version, applied_at_ms) VALUES (?, ?)",
                        (1, int(time.time() * 1000)),
                    )
                connection.commit()
            except Exception:
                connection.rollback()
                raise
        self.fts_available = self._ensure_sqlite_fts()
        return self.health()

    def _ensure_sqlite_fts(self) -> bool:
        if self.database.backend != "sqlite":
            return False
        try:
            with self.database.connect() as connection:
                self.database._execute(
                    connection,
                    """
                    CREATE VIRTUAL TABLE IF NOT EXISTS memory_facts_fts
                    USING fts5(fact_id UNINDEXED, content, background, tokenize='unicode61')
                    """,
                )
                connection.commit()
            return True
        except Exception:
            return False

    def health(self) -> dict[str, Any]:
        try:
            with self.database.connect() as connection:
                row = self.database._fetchone(
                    connection,
                    "SELECT MAX(version) AS version FROM memory_schema_migrations",
                )
                counts = {}
                for table in ("memory_raw_logs", "memory_facts", "memory_scenarios", "memory_core"):
                    result = self.database._fetchone(connection, f"SELECT COUNT(*) AS total FROM {table}")
                    counts[table] = int((result or {}).get("total") or 0)
            return {
                "status": "ok",
                "backend": self.database.backend,
                "schema_version": int((row or {}).get("version") or 0),
                "fts_available": bool(self.fts_available),
                "counts": counts,
            }
        except Exception as exc:
            return {
                "status": "error",
                "backend": self.database.backend,
                "error": f"{type(exc).__name__}: {exc}",
            }

    def rollback(self, *, confirmed: bool = False) -> None:
        if not confirmed:
            raise RuntimeError("memory schema rollback requires confirmed=True")
        with self.database.connect() as connection:
            try:
                self.database._begin(connection, immediate=True)
                if self.database.backend == "sqlite":
                    self.database._execute(connection, "DROP TABLE IF EXISTS memory_facts_fts")
                for table in (
                    "memory_core",
                    "memory_scenarios",
                    "memory_facts",
                    "memory_raw_logs",
                    "memory_schema_migrations",
                ):
                    self.database._execute(connection, f"DROP TABLE IF EXISTS {table}")
                connection.commit()
            except Exception:
                connection.rollback()
                raise


__all__ = ["MEMORY_SCHEMA_VERSION", "MemoryMigrationManager"]
