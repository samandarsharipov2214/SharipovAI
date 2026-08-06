"""Repository for passive memory records stored in the canonical database."""
from __future__ import annotations

import hashlib
import json
import math
import re
import time
from dataclasses import dataclass
from typing import Any, Sequence

from storage import ProjectDatabase

from .metrics import observe_memory_search, record_memory_fact, record_memory_raw_log
from .migrations import MemoryMigrationManager
from .models import FactCreate, MemoryFact, MemoryStatus, RawLog, RawLogCreate, RawLogStatus

_TOKEN_RE = re.compile(r"[\w\-./:]+", re.UNICODE)
_ALLOWED_TRANSITIONS: dict[MemoryStatus, set[MemoryStatus]] = {
    MemoryStatus.EXTRACTED: {MemoryStatus.VERIFIED, MemoryStatus.REVOKED, MemoryStatus.SUPERSEDED},
    MemoryStatus.VERIFIED: {MemoryStatus.ACTIVE, MemoryStatus.REVOKED, MemoryStatus.SUPERSEDED},
    MemoryStatus.ACTIVE: {MemoryStatus.REVOKED, MemoryStatus.SUPERSEDED},
    MemoryStatus.SUPERSEDED: set(),
    MemoryStatus.REVOKED: set(),
}


@dataclass(frozen=True, slots=True)
class SearchHit:
    fact: MemoryFact
    score: float
    lexical_rank: int | None = None
    vector_rank: int | None = None


class MemoryRepository:
    """Strictly isolated L0/L1 repository on the existing ProjectDatabase."""

    def __init__(self, database: ProjectDatabase | None = None) -> None:
        self.database = database or ProjectDatabase()
        self.migrations = MemoryMigrationManager(self.database)
        self._initialized = False

    def initialize(self) -> dict[str, Any]:
        health = self.migrations.initialize()
        self._initialized = health.get("status") == "ok"
        return health

    def health(self) -> dict[str, Any]:
        return self.migrations.health() if self._initialized else {"status": "not_initialized"}

    def save_raw_log(self, item: RawLogCreate) -> RawLog:
        self._require_initialized()
        created_at_ms = item.created_at_ms or _now_ms()
        digest = _digest(
            item.team_id,
            item.user_id,
            item.agent_id,
            item.session_id,
            item.message_role,
            item.content,
            item.source_ref,
        )
        log_id = f"memlog_{digest[:40]}"
        with self.database.connect() as connection:
            try:
                self.database._begin(connection)
                self.database._execute(
                    connection,
                    """
                    INSERT INTO memory_raw_logs(
                        log_id, team_id, user_id, agent_id, session_id, message_role,
                        content, source_ref, source_digest, processing_status,
                        metadata_json, created_at_ms, processed_at_ms
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(source_digest) DO NOTHING
                    """,
                    (
                        log_id,
                        item.team_id,
                        item.user_id,
                        item.agent_id,
                        item.session_id,
                        item.message_role,
                        item.content,
                        item.source_ref,
                        digest,
                        RawLogStatus.PENDING.value,
                        _json(item.metadata),
                        created_at_ms,
                        None,
                    ),
                )
                connection.commit()
            except Exception:
                connection.rollback()
                raise
        row = self._raw_by_digest(digest)
        if row is None:
            raise RuntimeError("raw memory insert did not produce a record")
        record_memory_raw_log()
        return _raw_from_row(row)

    def list_pending_raw_logs(self, *, limit: int = 10) -> list[RawLog]:
        self._require_initialized()
        bounded = min(max(int(limit), 1), 100)
        with self.database.connect() as connection:
            rows = self.database._fetchall(
                connection,
                """
                SELECT * FROM memory_raw_logs
                WHERE processing_status = ?
                ORDER BY created_at_ms ASC, log_id ASC LIMIT ?
                """,
                (RawLogStatus.PENDING.value, bounded),
            )
        return [_raw_from_row(row) for row in rows]

    def mark_raw_log(self, log_id: str, status: RawLogStatus) -> None:
        self._require_initialized()
        processed_at_ms = None if status is RawLogStatus.PENDING else _now_ms()
        with self.database.connect() as connection:
            try:
                self.database._begin(connection)
                cursor = self.database._execute(
                    connection,
                    "UPDATE memory_raw_logs SET processing_status = ?, processed_at_ms = ? WHERE log_id = ?",
                    (status.value, processed_at_ms, _identifier(log_id, "log_id")),
                )
                if getattr(cursor, "rowcount", 0) == 0:
                    raise KeyError(f"unknown memory log: {log_id}")
                connection.commit()
            except Exception:
                connection.rollback()
                raise

    def save_fact(self, item: FactCreate, *, status: MemoryStatus = MemoryStatus.EXTRACTED) -> MemoryFact:
        self._require_initialized()
        if status is MemoryStatus.ACTIVE:
            raise ValueError("facts cannot be created ACTIVE; manual approval is required")
        digest = _digest(
            item.team_id,
            item.user_id,
            item.agent_id,
            item.content,
            item.background,
            item.fact_type,
            item.source_ref,
        )
        fact_id = f"memfact_{digest[:40]}"
        now = _now_ms()
        with self.database.connect() as connection:
            try:
                self.database._begin(connection)
                self.database._execute(
                    connection,
                    """
                    INSERT INTO memory_facts(
                        fact_id, team_id, user_id, agent_id, session_id, content,
                        background, fact_type, status, priority, source_log_id,
                        source_ref, source_digest, embedding_json, metadata_json,
                        created_at_ms, updated_at_ms
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(team_id, agent_id, user_id, source_digest) DO NOTHING
                    """,
                    (
                        fact_id,
                        item.team_id,
                        item.user_id,
                        item.agent_id,
                        item.session_id,
                        item.content,
                        item.background,
                        item.fact_type,
                        status.value,
                        item.priority,
                        item.source_log_id,
                        item.source_ref,
                        digest,
                        _json(item.embedding) if item.embedding is not None else None,
                        _json(item.metadata),
                        now,
                        now,
                    ),
                )
                connection.commit()
            except Exception:
                connection.rollback()
                raise
        fact = self.get_fact_by_source(
            team_id=item.team_id,
            agent_id=item.agent_id,
            user_id=item.user_id,
            source_digest=digest,
        )
        if fact is None:
            raise RuntimeError("memory fact insert did not produce a record")
        self._sync_fts(fact)
        record_memory_fact(fact.status.value)
        return fact

    def get_fact(self, fact_id: str) -> MemoryFact | None:
        self._require_initialized()
        with self.database.connect() as connection:
            row = self.database._fetchone(
                connection,
                "SELECT * FROM memory_facts WHERE fact_id = ?",
                (_identifier(fact_id, "fact_id"),),
            )
        return _fact_from_row(row) if row else None

    def get_fact_by_source(
        self,
        *,
        team_id: str,
        agent_id: str,
        user_id: str,
        source_digest: str,
    ) -> MemoryFact | None:
        with self.database.connect() as connection:
            row = self.database._fetchone(
                connection,
                """
                SELECT * FROM memory_facts
                WHERE team_id = ? AND agent_id = ? AND user_id = ? AND source_digest = ?
                """,
                (team_id, agent_id, user_id, source_digest),
            )
        return _fact_from_row(row) if row else None

    def get_facts_by_agent(
        self,
        agent_id: str,
        *,
        user_id: str | None = None,
        team_id: str | None = None,
        statuses: Sequence[MemoryStatus] | None = None,
        limit: int = 100,
    ) -> list[MemoryFact]:
        self._require_initialized()
        clauses = ["agent_id = ?"]
        params: list[Any] = [_identifier(agent_id, "agent_id")]
        if user_id is not None:
            clauses.append("user_id = ?")
            params.append(_identifier(user_id, "user_id"))
        if team_id is not None:
            clauses.append("team_id = ?")
            params.append(_identifier(team_id, "team_id"))
        selected = tuple(statuses or (MemoryStatus.VERIFIED, MemoryStatus.ACTIVE))
        clauses.append(f"status IN ({','.join('?' for _ in selected)})")
        params.extend(status.value for status in selected)
        params.append(min(max(int(limit), 1), 1000))
        with self.database.connect() as connection:
            rows = self.database._fetchall(
                connection,
                f"SELECT * FROM memory_facts WHERE {' AND '.join(clauses)} ORDER BY priority DESC, updated_at_ms DESC LIMIT ?",
                tuple(params),
            )
        return [_fact_from_row(row) for row in rows]

    def update_fact_status(
        self,
        fact_id: str,
        status: MemoryStatus,
        *,
        actor: str,
        rationale: str,
        manual_approval: bool = False,
    ) -> MemoryFact:
        self._require_initialized()
        current = self.get_fact(fact_id)
        if current is None:
            raise KeyError(f"unknown memory fact: {fact_id}")
        if status is current.status:
            return current
        if status not in _ALLOWED_TRANSITIONS[current.status]:
            raise ValueError(f"invalid memory transition {current.status.value}->{status.value}")
        if status is MemoryStatus.ACTIVE and not manual_approval:
            raise PermissionError("ACTIVE memory requires manual approval")
        metadata = dict(current.metadata)
        metadata["status_change"] = {
            "from": current.status.value,
            "to": status.value,
            "actor": _identifier(actor, "actor"),
            "rationale": _text(rationale, "rationale", 2000),
            "manual_approval": bool(manual_approval),
            "changed_at_ms": _now_ms(),
        }
        with self.database.connect() as connection:
            try:
                self.database._begin(connection, immediate=True)
                self.database._execute(
                    connection,
                    "UPDATE memory_facts SET status = ?, metadata_json = ?, updated_at_ms = ? WHERE fact_id = ? AND status = ?",
                    (status.value, _json(metadata), _now_ms(), current.fact_id, current.status.value),
                )
                connection.commit()
            except Exception:
                connection.rollback()
                raise
        updated = self.get_fact(current.fact_id)
        if updated is None or updated.status is not status:
            raise RuntimeError("memory fact status update was not applied")
        record_memory_fact(status.value)
        return updated

    def search_facts(
        self,
        query: str,
        *,
        agent_id: str,
        user_id: str,
        team_id: str | None = None,
        limit: int = 5,
        statuses: Sequence[MemoryStatus] = (MemoryStatus.VERIFIED, MemoryStatus.ACTIVE),
        query_embedding: Sequence[float] | None = None,
        candidate_limit: int = 100,
    ) -> list[SearchHit]:
        self._require_initialized()
        started = time.perf_counter()
        bounded_limit = min(max(int(limit), 1), 20)
        bounded_candidates = min(max(int(candidate_limit), bounded_limit), 1000)
        lexical = self._lexical_search(
            query,
            agent_id=agent_id,
            user_id=user_id,
            team_id=team_id,
            statuses=statuses,
            limit=bounded_candidates,
        )
        vector = self._vector_search(
            query_embedding,
            agent_id=agent_id,
            user_id=user_id,
            team_id=team_id,
            statuses=statuses,
            limit=bounded_candidates,
        )
        ranked = _rrf(lexical, vector)
        hits: list[SearchHit] = []
        for fact_id, score, lexical_rank, vector_rank in ranked[:bounded_limit]:
            fact = self.get_fact(fact_id)
            if fact is not None:
                hits.append(SearchHit(fact, score, lexical_rank, vector_rank))
        observe_memory_search(time.perf_counter() - started, "hybrid" if vector else "lexical")
        return hits

    def stats(self) -> dict[str, Any]:
        self._require_initialized()
        with self.database.connect() as connection:
            raw = self.database._fetchone(connection, "SELECT COUNT(*) AS total FROM memory_raw_logs") or {}
            rows = self.database._fetchall(connection, "SELECT status, COUNT(*) AS total FROM memory_facts GROUP BY status")
        return {
            "raw_logs": int(raw.get("total") or 0),
            "facts": {str(row["status"]): int(row["total"]) for row in rows},
        }

    def _raw_by_digest(self, digest: str) -> dict[str, Any] | None:
        with self.database.connect() as connection:
            return self.database._fetchone(
                connection,
                "SELECT * FROM memory_raw_logs WHERE source_digest = ?",
                (digest,),
            )

    def _lexical_search(
        self,
        query: str,
        *,
        agent_id: str,
        user_id: str,
        team_id: str | None,
        statuses: Sequence[MemoryStatus],
        limit: int,
    ) -> list[str]:
        clauses = ["agent_id = ?", "user_id = ?"]
        params: list[Any] = [_identifier(agent_id, "agent_id"), _identifier(user_id, "user_id")]
        if team_id is not None:
            clauses.append("team_id = ?")
            params.append(_identifier(team_id, "team_id"))
        clauses.append(f"status IN ({','.join('?' for _ in statuses)})")
        params.extend(status.value for status in statuses)
        fts_ids: list[str] = []
        if self.database.backend == "sqlite" and self.migrations.fts_available:
            fts_query = _fts_query(query)
            if fts_query:
                try:
                    with self.database.connect() as connection:
                        rows = self.database._fetchall(
                            connection,
                            "SELECT fact_id FROM memory_facts_fts WHERE memory_facts_fts MATCH ? ORDER BY bm25(memory_facts_fts) LIMIT ?",
                            (fts_query, limit * 4),
                        )
                    fts_ids = [str(row["fact_id"]) for row in rows]
                except Exception:
                    fts_ids = []
        if fts_ids:
            clauses.append(f"fact_id IN ({','.join('?' for _ in fts_ids)})")
            params.extend(fts_ids)
        else:
            operator = "ILIKE" if self.database.backend == "postgresql" else "LIKE"
            clauses.append(f"(content {operator} ? OR background {operator} ?)")
            pattern = f"%{query}%"
            params.extend((pattern, pattern))
        params.append(limit)
        with self.database.connect() as connection:
            rows = self.database._fetchall(
                connection,
                f"SELECT fact_id FROM memory_facts WHERE {' AND '.join(clauses)} ORDER BY priority DESC, updated_at_ms DESC LIMIT ?",
                tuple(params),
            )
        ordered = [str(row["fact_id"]) for row in rows]
        if fts_ids:
            positions = {fact_id: index for index, fact_id in enumerate(fts_ids)}
            ordered.sort(key=lambda fact_id: positions.get(fact_id, len(positions)))
        return ordered

    def _vector_search(
        self,
        query_embedding: Sequence[float] | None,
        *,
        agent_id: str,
        user_id: str,
        team_id: str | None,
        statuses: Sequence[MemoryStatus],
        limit: int,
    ) -> list[str]:
        if not query_embedding:
            return []
        clauses = ["agent_id = ?", "user_id = ?", "embedding_json IS NOT NULL"]
        params: list[Any] = [_identifier(agent_id, "agent_id"), _identifier(user_id, "user_id")]
        if team_id is not None:
            clauses.append("team_id = ?")
            params.append(_identifier(team_id, "team_id"))
        clauses.append(f"status IN ({','.join('?' for _ in statuses)})")
        params.extend(status.value for status in statuses)
        params.append(limit)
        with self.database.connect() as connection:
            rows = self.database._fetchall(
                connection,
                f"SELECT fact_id, embedding_json FROM memory_facts WHERE {' AND '.join(clauses)} ORDER BY updated_at_ms DESC LIMIT ?",
                tuple(params),
            )
        scored: list[tuple[float, str]] = []
        query_vector = [float(item) for item in query_embedding]
        for row in rows:
            try:
                score = _cosine(query_vector, [float(item) for item in json.loads(row["embedding_json"])])
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
            if score > 0:
                scored.append((score, str(row["fact_id"])))
        scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
        return [fact_id for _score, fact_id in scored]

    def _sync_fts(self, fact: MemoryFact) -> None:
        if self.database.backend != "sqlite" or not self.migrations.fts_available:
            return
        try:
            with self.database.connect() as connection:
                self.database._begin(connection)
                self.database._execute(connection, "DELETE FROM memory_facts_fts WHERE fact_id = ?", (fact.fact_id,))
                self.database._execute(
                    connection,
                    "INSERT INTO memory_facts_fts(fact_id, content, background) VALUES (?, ?, ?)",
                    (fact.fact_id, fact.content, fact.background),
                )
                connection.commit()
        except Exception:
            return

    def _require_initialized(self) -> None:
        if not self._initialized:
            raise RuntimeError("MemoryRepository is not initialized")


def _raw_from_row(row: dict[str, Any]) -> RawLog:
    return RawLog(
        log_id=row["log_id"],
        team_id=row["team_id"],
        user_id=row["user_id"],
        agent_id=row["agent_id"],
        session_id=row["session_id"],
        message_role=row["message_role"],
        content=row["content"],
        source_ref=row["source_ref"],
        source_digest=row["source_digest"],
        processing_status=RawLogStatus(row["processing_status"]),
        metadata=json.loads(row["metadata_json"]),
        created_at_ms=int(row["created_at_ms"]),
        processed_at_ms=int(row["processed_at_ms"]) if row.get("processed_at_ms") is not None else None,
    )


def _fact_from_row(row: dict[str, Any]) -> MemoryFact:
    return MemoryFact(
        fact_id=row["fact_id"],
        team_id=row["team_id"],
        user_id=row["user_id"],
        agent_id=row["agent_id"],
        session_id=row["session_id"],
        content=row["content"],
        background=row["background"],
        fact_type=row["fact_type"],
        status=MemoryStatus(row["status"]),
        priority=int(row["priority"]),
        source_log_id=row.get("source_log_id"),
        source_ref=row["source_ref"],
        source_digest=row["source_digest"],
        embedding=json.loads(row["embedding_json"]) if row.get("embedding_json") else None,
        metadata=json.loads(row["metadata_json"]),
        created_at_ms=int(row["created_at_ms"]),
        updated_at_ms=int(row["updated_at_ms"]),
    )


def _rrf(lexical: Sequence[str], vector: Sequence[str], k: int = 60) -> list[tuple[str, float, int | None, int | None]]:
    scores: dict[str, float] = {}
    lexical_rank: dict[str, int] = {}
    vector_rank: dict[str, int] = {}
    for rank, fact_id in enumerate(lexical, start=1):
        lexical_rank[fact_id] = rank
        scores[fact_id] = scores.get(fact_id, 0.0) + 1.0 / (k + rank)
    for rank, fact_id in enumerate(vector, start=1):
        vector_rank[fact_id] = rank
        scores[fact_id] = scores.get(fact_id, 0.0) + 1.0 / (k + rank)
    return sorted(
        ((fact_id, round(score, 9), lexical_rank.get(fact_id), vector_rank.get(fact_id)) for fact_id, score in scores.items()),
        key=lambda item: (item[1], -(item[2] or 10_000), -(item[3] or 10_000), item[0]),
        reverse=True,
    )


def _cosine(left: Sequence[float], right: Sequence[float]) -> float:
    if not left or len(left) != len(right):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    return 0.0 if left_norm == 0 or right_norm == 0 else dot / (left_norm * right_norm)


def _fts_query(value: str) -> str:
    tokens = [token.replace('"', "") for token in _TOKEN_RE.findall(value)[:20]]
    return " OR ".join(f'"{token}"' for token in tokens if token)


def _identifier(value: str, name: str) -> str:
    clean = str(value).strip()
    if not clean or len(clean) > 200 or "\x00" in clean:
        raise ValueError(f"{name} must contain 1..200 safe characters")
    return clean


def _text(value: str, name: str, limit: int) -> str:
    clean = str(value).strip()
    if not clean or len(clean) > limit or "\x00" in clean:
        raise ValueError(f"{name} must contain 1..{limit} safe characters")
    return clean


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _digest(*parts: Any) -> str:
    return hashlib.sha256("\x1f".join(str(part) for part in parts).encode("utf-8")).hexdigest()


def _now_ms() -> int:
    return int(time.time() * 1000)


__all__ = ["MemoryRepository", "SearchHit"]
