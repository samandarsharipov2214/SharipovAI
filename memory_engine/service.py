"""Fail-safe Memory Layer service: passive collection and context only on request."""
from __future__ import annotations

import re
import threading
import time
from collections.abc import Mapping
from typing import Any

from storage import ProjectDatabase

from .config import MemorySettings
from .extraction import EmbeddingProvider, FactExtractor, embedding_provider_from_settings
from .metrics import set_memory_circuit_open
from .models import ContextItem, FactCreate, MemoryStatus, RawLog, RawLogCreate, RawLogStatus
from .repository import MemoryRepository
from .verification import FactVerifier

_SECRET_PATTERNS = (
    re.compile(r"(?i)\b(authorization|api[_-]?key|password|secret|token)\b\s*[:=]\s*[^\s,;]+"),
    re.compile(r"\b(?:sk|ghp|github_pat|xox[baprs])-[-A-Za-z0-9_]{12,}\b"),
)


class MemoryService:
    """Memory service with bounded failure isolation and no execution authority."""

    def __init__(
        self,
        database: ProjectDatabase | None = None,
        *,
        settings: MemorySettings | None = None,
        repository: MemoryRepository | None = None,
        extractor: FactExtractor | None = None,
        verifier: FactVerifier | None = None,
        embedding_provider: EmbeddingProvider | None = None,
    ) -> None:
        self.settings = settings or MemorySettings.from_env()
        self.database = database or ProjectDatabase()
        self.repository = repository or MemoryRepository(self.database)
        self.extractor = extractor or FactExtractor.from_settings(self.settings)
        self.verifier = verifier or FactVerifier()
        self.embedding_provider = embedding_provider or embedding_provider_from_settings(self.settings)
        self._lock = threading.RLock()
        self._initialized = False
        self._consecutive_failures = 0
        self._disabled_until = 0.0
        self._last_error = ""

    @property
    def enabled(self) -> bool:
        return self.settings.enabled and time.time() >= self._disabled_until

    @property
    def context_enabled(self) -> bool:
        return self.enabled and self.settings.context_injection_enabled

    def initialize(self) -> dict[str, Any]:
        if not self.settings.enabled:
            return self.health()
        try:
            result = self.repository.initialize()
            self._initialized = result.get("status") == "ok"
            self._record_success()
            return self.health()
        except Exception as exc:
            self._record_failure(exc)
            return self.health()

    def record_dialog(
        self,
        *,
        team_id: str,
        user_id: str,
        agent_id: str,
        session_id: str,
        message: str,
        source_ref: str,
        role: str = "event",
        metadata: Mapping[str, Any] | None = None,
        created_at_ms: int | None = None,
    ) -> RawLog | None:
        if not self.enabled:
            return None
        self._ensure_initialized()
        redacted = _redact(str(message))[: self.settings.max_input_chars]
        if not redacted.strip():
            return None
        try:
            result = self.repository.save_raw_log(
                RawLogCreate(
                    team_id=team_id,
                    user_id=user_id,
                    agent_id=agent_id,
                    session_id=session_id,
                    message_role=role,
                    content=redacted,
                    source_ref=source_ref,
                    metadata={**dict(metadata or {}), "secrets_redacted": redacted != str(message)},
                    created_at_ms=created_at_ms,
                )
            )
            self._record_success()
            return result
        except Exception as exc:
            self._record_failure(exc)
            return None

    def get_context(
        self,
        *,
        agent_id: str,
        user_id: str,
        query_text: str,
        team_id: str | None = None,
        limit: int | None = None,
    ) -> list[ContextItem]:
        if not self.context_enabled:
            return []
        self._ensure_initialized()
        try:
            query_embedding = self.embedding_provider.embed(query_text) if self.embedding_provider else None
            hits = self.repository.search_facts(
                query_text,
                agent_id=agent_id,
                user_id=user_id,
                team_id=team_id or self.settings.team_id,
                limit=limit or self.settings.context_limit,
                statuses=(MemoryStatus.VERIFIED, MemoryStatus.ACTIVE),
                query_embedding=query_embedding,
                candidate_limit=self.settings.search_candidate_limit,
            )
            self._record_success()
            return [
                ContextItem(
                    fact_id=hit.fact.fact_id,
                    content=hit.fact.content,
                    background=hit.fact.background,
                    fact_type=hit.fact.fact_type,
                    status=hit.fact.status,
                    priority=hit.fact.priority,
                    score=hit.score,
                    source_ref=hit.fact.source_ref,
                )
                for hit in hits
            ]
        except Exception as exc:
            self._record_failure(exc)
            return []

    def get_recent_dialog(
        self,
        *,
        agent_id: str,
        user_id: str,
        team_id: str | None = None,
        limit: int | None = None,
    ) -> list[str]:
        """Return bounded, redacted dialogue continuity with no fact authority."""

        if not self.context_enabled:
            return []
        try:
            self._ensure_initialized()
            logs = self.repository.list_recent_raw_logs(
                team_id=team_id or self.settings.team_id,
                user_id=user_id,
                agent_id=agent_id,
                limit=limit or self.settings.context_limit,
            )
            self._record_success()
            return [f"{item.message_role}: {item.content}" for item in logs]
        except Exception as exc:
            self._record_failure(exc)
            return []

    def extract_pending(self, *, limit: int | None = None) -> dict[str, Any]:
        if not self.enabled or not self.settings.extraction_enabled:
            return {"status": "disabled", "processed": 0, "facts": 0}
        self._ensure_initialized()
        processed = 0
        saved = 0
        errors: list[str] = []
        for raw in self.repository.list_pending_raw_logs(limit=limit or self.settings.extraction_batch_size):
            try:
                extracted = self.extractor.extract(raw)
                if not extracted:
                    self.repository.mark_raw_log(raw.log_id, RawLogStatus.SKIPPED)
                    processed += 1
                    continue
                for candidate in extracted:
                    embedding = self.embedding_provider.embed(candidate.content) if self.embedding_provider else None
                    fact = self.repository.save_fact(
                        FactCreate(
                            team_id=raw.team_id,
                            user_id=raw.user_id,
                            agent_id=raw.agent_id,
                            session_id=raw.session_id,
                            content=candidate.content,
                            background=candidate.background,
                            fact_type=candidate.fact_type,
                            priority=candidate.priority,
                            source_log_id=raw.log_id,
                            source_ref=raw.source_ref,
                            embedding=list(embedding) if embedding is not None else None,
                            metadata={"extracted_from": raw.log_id, "automatic_activation": False},
                        )
                    )
                    if self.settings.verification_enabled and fact.status is MemoryStatus.EXTRACTED:
                        existing = self.repository.get_facts_by_agent(
                            fact.agent_id,
                            user_id=fact.user_id,
                            team_id=fact.team_id,
                            statuses=(MemoryStatus.VERIFIED, MemoryStatus.ACTIVE),
                            limit=self.settings.search_candidate_limit,
                        )
                        verdict = self.verifier.verify(fact, existing)
                        self.repository.update_fact_status(
                            fact.fact_id,
                            verdict.status,
                            actor="memory_verifier",
                            rationale=verdict.rationale,
                            manual_approval=False,
                        )
                    saved += 1
                self.repository.mark_raw_log(raw.log_id, RawLogStatus.PROCESSED)
                processed += 1
                self._record_success()
            except Exception as exc:
                errors.append(f"{raw.log_id}:{type(exc).__name__}")
                try:
                    self.repository.mark_raw_log(raw.log_id, RawLogStatus.ERROR)
                except Exception:
                    pass
                self._record_failure(exc)
                if not self.enabled:
                    break
        return {
            "status": "ok" if not errors else "degraded",
            "processed": processed,
            "facts": saved,
            "errors": errors[:20],
            "automatic_activation": False,
            "execution_authority": False,
        }

    def approve_fact(self, fact_id: str, *, actor: str, rationale: str, manual_approval: bool) -> Any:
        if not self.enabled:
            raise RuntimeError("Memory Layer is disabled")
        self._ensure_initialized()
        return self.repository.update_fact_status(
            fact_id,
            MemoryStatus.ACTIVE,
            actor=actor,
            rationale=rationale,
            manual_approval=manual_approval,
        )

    def health(self) -> dict[str, Any]:
        flags = self.settings.flags()
        if not self.settings.enabled:
            return {
                "status": "disabled",
                "flags": flags,
                "execution_authority": False,
                "automatic_activation": False,
            }
        circuit_open = time.time() < self._disabled_until
        repository_health = self.repository.health() if self._initialized else {"status": "not_initialized"}
        status = "degraded" if circuit_open or repository_health.get("status") not in {"ok", "not_initialized"} else "ok"
        stats: dict[str, Any] = {}
        if self._initialized:
            try:
                stats = self.repository.stats()
            except Exception as exc:
                status = "degraded"
                self._last_error = f"{type(exc).__name__}: {exc}"
        return {
            "status": status,
            "flags": flags,
            "initialized": self._initialized,
            "repository": repository_health,
            "stats": stats,
            "circuit_open": circuit_open,
            "circuit_disabled_until_ms": int(self._disabled_until * 1000) if circuit_open else 0,
            "consecutive_failures": self._consecutive_failures,
            "last_error": self._last_error,
            "execution_authority": False,
            "automatic_activation": False,
            "financial_state_source": False,
        }

    def _ensure_initialized(self) -> None:
        if not self._initialized:
            result = self.initialize()
            if result.get("status") != "ok":
                raise RuntimeError("Memory Layer initialization failed")

    def _record_success(self) -> None:
        with self._lock:
            self._consecutive_failures = 0
            self._last_error = ""
            if self._disabled_until and time.time() >= self._disabled_until:
                self._disabled_until = 0.0
            set_memory_circuit_open(False)

    def _record_failure(self, exc: Exception) -> None:
        with self._lock:
            self._consecutive_failures += 1
            self._last_error = f"{type(exc).__name__}: {exc}"[:1000]
            if self._consecutive_failures >= self.settings.max_consecutive_failures:
                self._disabled_until = time.time() + self.settings.circuit_reset_seconds
                set_memory_circuit_open(True)


def _redact(value: str) -> str:
    result = value
    for pattern in _SECRET_PATTERNS:
        result = pattern.sub("[REDACTED_SECRET]", result)
    return result


__all__ = ["MemoryService"]
