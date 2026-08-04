"""Persistent learning from validated development fixes.

Source-of-truth fix and decision evidence lives in the canonical agent-learning
ledger (``agent_fixes``, ``agent_decisions`` and ``agent_decision_events``).
This service appends verified outcomes, builds deterministic derived indexes,
returns successful fixes as few-shot examples, and creates manual-only weekly
process optimization proposals. It never applies patches or changes runtime
execution flags.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import time
from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta, timezone
from pathlib import PurePosixPath
from typing import Any

from storage import ProjectDatabase

_PROJECTION_NAMESPACE = "development_learning_memory_projection"
_PROPOSALS_NAMESPACE = "development_learning_process_proposals"
_EVENTS_NAMESPACE = "development_learning_events"
_PROJECTION_KEY = "current"
_OUTCOME_EVENT_TYPE = "fix_outcome_recorded"
_SCHEMA_VERSION = 1
_TOKEN_RE = re.compile(r"[a-zA-Z_][a-zA-Z0-9_./:-]*|[\u0400-\u04ff][\u0400-\u04ff0-9_./:-]*")
_ERROR_TYPE_RE = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*(?:Error|Exception|Failure|Warning))\b")
_MODULE_RE = re.compile(r"(?:No module named|module)\s+['\"]?([A-Za-z_][A-Za-z0-9_.-]*)", re.IGNORECASE)
_GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_SENSITIVE_MARKERS = (
    "api_key",
    "apikey",
    "authorization",
    "cookie",
    "credential",
    "password",
    "private_key",
    "secret",
    "session",
    "token",
)


class DevelopmentLearningService:
    """Learning Engine owner for repair memory and few-shot curation."""

    def __init__(
        self,
        database: ProjectDatabase | None = None,
        *,
        feature_dimensions: int | None = None,
        memory_limit: int | None = None,
    ) -> None:
        self.database = database or ProjectDatabase()
        self.database.initialize()
        self.feature_dimensions = _bounded_int(
            feature_dimensions if feature_dimensions is not None else os.getenv("DEVELOPMENT_LEARNING_FEATURE_DIMENSIONS", "256"),
            minimum=32,
            maximum=4096,
            default=256,
        )
        self.memory_limit = _bounded_int(
            memory_limit if memory_limit is not None else os.getenv("DEVELOPMENT_LEARNING_MEMORY_LIMIT", "5000"),
            minimum=10,
            maximum=100_000,
            default=5000,
        )

    def record_fix_outcome(
        self,
        fix_id: str,
        decision_id: str,
        success: bool,
        result_sha: str,
        validation: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Append one verified, idempotent outcome to the agent decision ledger."""

        clean_fix_id = _clean_identifier(fix_id, "fix_id")
        clean_decision_id = _clean_identifier(decision_id, "decision_id")
        if not isinstance(success, bool):
            raise TypeError("success must be a bool")
        clean_result_sha = _clean_text(result_sha, limit=40).lower()
        if clean_result_sha and not _GIT_SHA_RE.fullmatch(clean_result_sha):
            raise ValueError("result_sha must be a 40-character lowercase Git SHA")
        if success and not clean_result_sha:
            raise ValueError("result_sha is required for a successful fix")
        if not isinstance(validation, Mapping):
            raise TypeError("validation must be a mapping")

        fix = self.database.get_agent_fix(clean_fix_id)
        if fix is None:
            raise KeyError(f"unknown fix_id: {clean_fix_id}")
        decision = self.database.get_agent_decision(clean_decision_id)
        if decision is None:
            raise KeyError(f"unknown decision_id: {clean_decision_id}")
        if str(decision.get("fix_id") or "") != clean_fix_id:
            raise ValueError("decision_id is not linked to fix_id")
        if bool(fix.get("success")) is not success:
            raise ValueError("outcome success conflicts with immutable agent_fixes evidence")
        applied_sha = str(fix.get("applied_sha") or "")
        if applied_sha and clean_result_sha and applied_sha != clean_result_sha:
            raise ValueError("result_sha conflicts with immutable agent_fixes applied_sha")

        safe_validation = _sanitize(validation)
        if not isinstance(safe_validation, dict):
            raise TypeError("validation must serialize to an object")
        fix_metadata = fix.get("metadata") if isinstance(fix.get("metadata"), Mapping) else {}
        metadata = _extract_metadata(
            {
                **dict(fix_metadata),
                **safe_validation,
                "error_signature": safe_validation.get("error_signature") or fix.get("error_signature"),
                "error_type": safe_validation.get("error_type") or fix.get("failure_class"),
            }
        )
        validation_digest = _digest(safe_validation)
        recorded_at_ms = _validation_timestamp(safe_validation) or _now_ms()
        payload = {
            "schema_version": _SCHEMA_VERSION,
            "fix_id": clean_fix_id,
            "decision_id": clean_decision_id,
            "success": success,
            "result_sha": clean_result_sha,
            "patch_sha256": str(fix.get("patch_sha256") or ""),
            "error_signature": metadata["error_signature"],
            "normalized_error": metadata["normalized_error"],
            "error_type": metadata["error_type"],
            "module": metadata["module"],
            "changed_files": metadata["changed_files"],
            "validation": safe_validation,
            "validation_sha256": validation_digest,
            "recorded_at_ms": recorded_at_ms,
            "execution_authority": False,
            "automatic_code_application": False,
            "runtime_flags_changed": False,
        }
        event_id = "devout_" + _digest(
            {
                "fix_id": clean_fix_id,
                "decision_id": clean_decision_id,
                "success": success,
                "result_sha": clean_result_sha,
                "validation_sha256": validation_digest,
            }
        )[:40]
        events = self.database.list_agent_decision_events(clean_decision_id, limit=2000)
        for event in events:
            if event.get("event_type") != _OUTCOME_EVENT_TYPE:
                continue
            existing = event.get("payload") if isinstance(event.get("payload"), Mapping) else {}
            if str(event.get("event_id") or "") == event_id:
                return {**dict(existing), "event_id": event_id, "idempotent": True}
            if str(existing.get("fix_id") or "") == clean_fix_id:
                raise ValueError("a different outcome is already recorded for this fix decision")

        self.database.append_agent_decision_event(
            event_id=event_id,
            decision_id=clean_decision_id,
            event_type=_OUTCOME_EVENT_TYPE,
            actor="learning_engine",
            payload=payload,
            created_at_ms=recorded_at_ms,
        )
        self.database.append_event(
            _EVENTS_NAMESPACE,
            "development_fix_outcome",
            clean_fix_id,
            {
                "decision_id": clean_decision_id,
                "success": success,
                "result_sha": clean_result_sha,
                "error_signature": metadata["error_signature"],
                "error_type": metadata["error_type"],
                "module": metadata["module"],
                "validation_sha256": validation_digest,
                "ledger_event_id": event_id,
            },
            created_at_ms=recorded_at_ms,
        )
        return {**payload, "event_id": event_id, "idempotent": False}

    def build_few_shot_pack(
        self,
        error_signature: str,
        normalized_error: str,
        changed_files: Sequence[str] | str,
        limit: int = 3,
    ) -> dict[str, Any]:
        """Find successful fixes by exact, typed-module, then cosine search."""

        bounded_limit = _bounded_int(limit, minimum=1, maximum=20, default=3)
        query = _extract_metadata(
            {
                "error_signature": error_signature,
                "normalized_error": normalized_error,
                "changed_files": changed_files,
            }
        )
        projection, projection_version = self._ensure_projection()
        items = projection.get("items") if isinstance(projection.get("items"), Mapping) else {}
        vectors = projection.get("vectors") if isinstance(projection.get("vectors"), Mapping) else {}
        exact_index = projection.get("exact_signature") if isinstance(projection.get("exact_signature"), Mapping) else {}
        typed_index = projection.get("error_type_module") if isinstance(projection.get("error_type_module"), Mapping) else {}
        query_vector = _feature_vector(query, self.feature_dimensions)
        records = {str(record.get("fix_id") or ""): record for record in self._outcome_records(success_only=True)}

        selected: list[dict[str, Any]] = []
        seen: set[str] = set()
        trace = {"exact_signature": 0, "error_type_module": 0, "cosine_similarity": 0}

        def add_candidate(candidate_fix_id: str, strategy: str, similarity: float) -> None:
            if len(selected) >= bounded_limit or candidate_fix_id in seen:
                return
            item = items.get(candidate_fix_id)
            record = records.get(candidate_fix_id)
            if not isinstance(item, Mapping) or not isinstance(record, Mapping):
                return
            selected.append(
                {
                    "fix_id": candidate_fix_id,
                    "decision_id": str(record.get("decision_id") or ""),
                    "match_strategy": strategy,
                    "similarity": round(max(min(float(similarity), 1.0), -1.0), 6),
                    "input": {
                        "error_signature": str(record.get("error_signature") or ""),
                        "normalized_error": str(record.get("normalized_error") or ""),
                        "error_type": str(record.get("error_type") or "unknown"),
                        "module": str(record.get("module") or "unknown"),
                        "changed_files": list(record.get("changed_files") or []),
                    },
                    "output": {
                        "result_sha": str(record.get("result_sha") or ""),
                        "patch": str(record.get("patch") or ""),
                        "patch_sha256": str(record.get("patch_sha256") or ""),
                        "test_evidence": record.get("test_evidence") if isinstance(record.get("test_evidence"), Mapping) else {},
                        "validation": record.get("validation") if isinstance(record.get("validation"), Mapping) else {},
                    },
                    "recorded_at_ms": int(record.get("recorded_at_ms") or 0),
                }
            )
            seen.add(candidate_fix_id)
            trace[strategy] += 1

        signature = query["error_signature"]
        if signature:
            for candidate_fix_id in _string_list(exact_index.get(signature)):
                add_candidate(candidate_fix_id, "exact_signature", 1.0)

        typed_key = _type_module_key(query["error_type"], query["module"])
        if len(selected) < bounded_limit and typed_key:
            for candidate_fix_id in _string_list(typed_index.get(typed_key)):
                vector = vectors.get(candidate_fix_id) if isinstance(vectors.get(candidate_fix_id), Mapping) else {}
                add_candidate(candidate_fix_id, "error_type_module", _cosine(query_vector, vector))

        if len(selected) < bounded_limit and query_vector:
            ranked: list[tuple[float, int, str]] = []
            for candidate_fix_id, vector in vectors.items():
                if candidate_fix_id in seen or not isinstance(vector, Mapping):
                    continue
                score = _cosine(query_vector, vector)
                if score <= 0:
                    continue
                item = items.get(candidate_fix_id) if isinstance(items.get(candidate_fix_id), Mapping) else {}
                ranked.append((score, int(item.get("recorded_at_ms") or 0), str(candidate_fix_id)))
            ranked.sort(key=lambda row: (row[0], row[1], row[2]), reverse=True)
            for score, _timestamp, candidate_fix_id in ranked:
                add_candidate(candidate_fix_id, "cosine_similarity", score)

        return {
            "status": "ok" if selected else "empty",
            "query": query,
            "examples": selected,
            "count": len(selected),
            "limit": bounded_limit,
            "selection_order": ["exact_signature", "error_type_module", "cosine_similarity"],
            "selection_trace": trace,
            "projection_version": projection_version,
            "projection_source_sha256": str(projection.get("source_sha256") or ""),
            "feature_dimensions": self.feature_dimensions,
            "execution_authority": False,
            "automatic_code_application": False,
        }

    def rebuild_memory_projection(self) -> dict[str, Any]:
        """Rebuild exact, typed-module and feature-hashing indexes."""

        records = self._outcome_records(success_only=True)
        source_digest = _records_digest(records)
        current = self.database.get_json(_PROJECTION_NAMESPACE, _PROJECTION_KEY)
        if current is not None:
            value = dict(current["value"])
            if (
                str(value.get("source_sha256") or "") == source_digest
                and int(value.get("feature_dimensions") or 0) == self.feature_dimensions
                and int(value.get("schema_version") or 0) == _SCHEMA_VERSION
            ):
                return {
                    "status": "ok",
                    "successful_fix_count": int(value.get("successful_fix_count") or 0),
                    "source_sha256": source_digest,
                    "feature_dimensions": self.feature_dimensions,
                    "projection_version": int(current["version"]),
                    "idempotent": True,
                    "execution_authority": False,
                }

        exact: dict[str, list[str]] = {}
        typed: dict[str, list[str]] = {}
        vectors: dict[str, dict[str, float]] = {}
        items: dict[str, dict[str, Any]] = {}
        for record in records:
            fix_id = str(record.get("fix_id") or "")
            if not fix_id:
                continue
            signature = str(record.get("error_signature") or "")
            error_type = str(record.get("error_type") or "unknown")
            module = str(record.get("module") or "unknown")
            if signature:
                exact.setdefault(signature, []).append(fix_id)
            typed_key = _type_module_key(error_type, module)
            if typed_key:
                typed.setdefault(typed_key, []).append(fix_id)
            metadata = {
                "error_signature": signature,
                "normalized_error": str(record.get("normalized_error") or ""),
                "error_type": error_type,
                "module": module,
                "changed_files": list(record.get("changed_files") or []),
            }
            vectors[fix_id] = _feature_vector(metadata, self.feature_dimensions)
            items[fix_id] = {
                **metadata,
                "decision_id": str(record.get("decision_id") or ""),
                "result_sha": str(record.get("result_sha") or ""),
                "patch_sha256": str(record.get("patch_sha256") or ""),
                "recorded_at_ms": int(record.get("recorded_at_ms") or 0),
                "validation_sha256": str(record.get("validation_sha256") or ""),
            }

        projection = {
            "schema_version": _SCHEMA_VERSION,
            "source_sha256": source_digest,
            "successful_fix_count": len(items),
            "feature_dimensions": self.feature_dimensions,
            "exact_signature": exact,
            "error_type_module": typed,
            "vectors": vectors,
            "items": items,
            "rebuilt_at_ms": _now_ms(),
            "execution_authority": False,
            "automatic_code_application": False,
            "runtime_flags_changed": False,
        }
        expected_version = int(current["version"]) if current else 0
        version = self.database.put_json(
            _PROJECTION_NAMESPACE,
            _PROJECTION_KEY,
            projection,
            expected_version=expected_version,
        )
        self.database.append_event(
            _EVENTS_NAMESPACE,
            "development_memory_projection",
            _PROJECTION_KEY,
            {
                "source_sha256": source_digest,
                "successful_fix_count": len(items),
                "feature_dimensions": self.feature_dimensions,
                "projection_version": version,
            },
        )
        return {
            "status": "ok",
            "successful_fix_count": len(items),
            "source_sha256": source_digest,
            "feature_dimensions": self.feature_dimensions,
            "projection_version": version,
            "idempotent": False,
            "execution_authority": False,
        }

    def run_weekly_process_review(self, now_ms: int) -> dict[str, Any]:
        """Review the previous completed UTC week and persist one proposal."""

        timestamp = int(now_ms)
        if timestamp <= 0:
            raise ValueError("now_ms must be positive")
        projection = self.rebuild_memory_projection()
        week_start_ms, week_end_ms = _previous_week_window(timestamp)
        proposal_id = "process_optimization_" + datetime.fromtimestamp(
            week_start_ms / 1000,
            tz=timezone.utc,
        ).strftime("%Y%m%d")
        existing = self.database.get_json(_PROPOSALS_NAMESPACE, proposal_id)
        if existing is not None:
            return {**dict(existing["value"]), "version": int(existing["version"]), "idempotent": True}

        records = [
            record
            for record in self._outcome_records(success_only=False)
            if week_start_ms <= int(record.get("recorded_at_ms") or 0) < week_end_ms
        ]
        successful = [record for record in records if record.get("success") is True]
        failed = [record for record in records if record.get("success") is not True]
        signature_counts = Counter(
            str(record.get("error_signature") or "")
            for record in records
            if str(record.get("error_signature") or "")
        )
        error_type_counts = Counter(str(record.get("error_type") or "unknown") for record in records)
        module_counts = Counter(str(record.get("module") or "unknown") for record in records)
        failed_module_counts = Counter(str(record.get("module") or "unknown") for record in failed)
        failed_checks: Counter[str] = Counter()
        missing_metadata = 0
        for record in records:
            if not record.get("error_signature") or not record.get("normalized_error") or not record.get("changed_files"):
                missing_metadata += 1
            validation = record.get("validation") if isinstance(record.get("validation"), Mapping) else {}
            checks = validation.get("checks") if isinstance(validation.get("checks"), Mapping) else {}
            for name, passed in checks.items():
                if passed is False:
                    failed_checks[str(name)] += 1

        total = len(records)
        success_count = len(successful)
        success_rate = round(success_count / total, 6) if total else 0.0
        repeated_signatures = [
            {"error_signature": signature, "count": count}
            for signature, count in signature_counts.most_common()
            if count > 1
        ]
        module_hotspots = [
            {"module": module, "failed_count": count}
            for module, count in failed_module_counts.most_common(10)
            if module != "unknown" and count > 0
        ]
        metrics = {
            "total_fixes": total,
            "successful_fixes": success_count,
            "failed_fixes": len(failed),
            "success_rate": success_rate,
            "unique_error_signatures": len(signature_counts),
            "repeated_error_signature_count": len(repeated_signatures),
            "missing_search_metadata_count": missing_metadata,
            "error_types": dict(error_type_counts.most_common(20)),
            "modules": dict(module_counts.most_common(20)),
            "failed_validation_checks": dict(failed_checks.most_common(20)),
        }
        findings = _process_findings(metrics, repeated_signatures, module_hotspots)
        recommendations = _process_recommendations(metrics, repeated_signatures, module_hotspots, failed_checks)
        evidence_fix_ids = sorted(str(record.get("fix_id") or "") for record in records if record.get("fix_id"))
        evidence_digest = _digest(
            {
                "week_start_ms": week_start_ms,
                "week_end_ms": week_end_ms,
                "metrics": metrics,
                "findings": findings,
                "recommendations": recommendations,
                "fix_ids": evidence_fix_ids,
                "projection_source_sha256": projection["source_sha256"],
            }
        )
        proposal = {
            "schema_version": _SCHEMA_VERSION,
            "proposal_id": proposal_id,
            "proposal_type": "process_optimization",
            "status": "proposed",
            "review_window": {"start_ms": week_start_ms, "end_ms": week_end_ms},
            "reviewed_at_ms": timestamp,
            "metrics": metrics,
            "findings": findings,
            "recommendations": recommendations,
            "module_hotspots": module_hotspots,
            "repeated_signatures": repeated_signatures[:20],
            "evidence_fix_ids": evidence_fix_ids[:500],
            "evidence_fix_count": len(evidence_fix_ids),
            "evidence_sha256": evidence_digest,
            "memory_projection": projection,
            "requires_manual_approval": True,
            "execution_authority": False,
            "automatic_code_application": False,
            "automatic_execution_promotion": False,
            "runtime_flags_changed": False,
        }
        version = self.database.put_json(
            _PROPOSALS_NAMESPACE,
            proposal_id,
            proposal,
            expected_version=0,
        )
        self.database.append_event(
            _EVENTS_NAMESPACE,
            "process_optimization",
            proposal_id,
            {
                "week_start_ms": week_start_ms,
                "week_end_ms": week_end_ms,
                "total_fixes": total,
                "success_rate": success_rate,
                "evidence_sha256": evidence_digest,
                "requires_manual_approval": True,
            },
            created_at_ms=timestamp,
        )
        return {**proposal, "version": version, "idempotent": False}

    def _ensure_projection(self) -> tuple[dict[str, Any], int]:
        records = self._outcome_records(success_only=True)
        source_digest = _records_digest(records)
        current = self.database.get_json(_PROJECTION_NAMESPACE, _PROJECTION_KEY)
        if (
            current is None
            or str(current["value"].get("source_sha256") or "") != source_digest
            or int(current["value"].get("feature_dimensions") or 0) != self.feature_dimensions
            or int(current["value"].get("schema_version") or 0) != _SCHEMA_VERSION
        ):
            self.rebuild_memory_projection()
            current = self.database.get_json(_PROJECTION_NAMESPACE, _PROJECTION_KEY)
        if current is None:  # pragma: no cover - defensive persistence guard
            raise RuntimeError("development learning projection was not persisted")
        return dict(current["value"]), int(current["version"])

    def _outcome_records(self, *, success_only: bool) -> list[dict[str, Any]]:
        clauses = ["e.event_type = ?"]
        params: list[Any] = [_OUTCOME_EVENT_TYPE]
        if success_only:
            clauses.append("f.success = ?")
            params.append(1)
        params.append(self.memory_limit)
        query = f"""
            SELECT e.event_id, e.decision_id, e.payload_json, e.created_at_ms,
                   f.fix_id, f.error_signature AS fix_error_signature,
                   f.failure_class, f.patch, f.patch_sha256, f.success AS fix_success,
                   f.source, f.base_sha, f.applied_sha, f.attempt_count,
                   f.test_evidence_json, f.metadata_json
            FROM agent_decision_events e
            JOIN agent_decisions d ON d.decision_id = e.decision_id
            JOIN agent_fixes f ON f.fix_id = d.fix_id
            WHERE {' AND '.join(clauses)}
            ORDER BY e.created_at_ms DESC, e.event_id DESC
            LIMIT ?
        """
        with self.database.connect() as connection:
            rows = self.database._fetchall(connection, query, tuple(params))
        records: list[dict[str, Any]] = []
        seen: set[str] = set()
        for row in rows:
            fix_id = str(row["fix_id"])
            if fix_id in seen:
                continue
            payload = json.loads(row["payload_json"])
            if not isinstance(payload, Mapping):
                continue
            validation = payload.get("validation") if isinstance(payload.get("validation"), Mapping) else {}
            fix_metadata = json.loads(row["metadata_json"])
            if not isinstance(fix_metadata, Mapping):
                fix_metadata = {}
            metadata = _extract_metadata(
                {
                    **dict(fix_metadata),
                    **dict(payload),
                    "error_signature": payload.get("error_signature") or row["fix_error_signature"],
                    "error_type": payload.get("error_type") or row["failure_class"],
                }
            )
            records.append(
                {
                    **dict(payload),
                    **metadata,
                    "fix_id": fix_id,
                    "decision_id": str(row["decision_id"]),
                    "success": bool(row["fix_success"]),
                    "result_sha": str(payload.get("result_sha") or row["applied_sha"] or ""),
                    "patch": str(row["patch"]),
                    "patch_sha256": str(row["patch_sha256"]),
                    "source": str(row["source"]),
                    "base_sha": str(row["base_sha"] or ""),
                    "attempt_count": int(row["attempt_count"]),
                    "test_evidence": json.loads(row["test_evidence_json"]),
                    "validation": dict(validation),
                    "recorded_at_ms": int(payload.get("recorded_at_ms") or row["created_at_ms"]),
                    "ledger_event_id": str(row["event_id"]),
                }
            )
            seen.add(fix_id)
        return records


def _extract_metadata(value: Mapping[str, Any]) -> dict[str, Any]:
    failure = value.get("failure") if isinstance(value.get("failure"), Mapping) else {}
    error_signature = _clean_text(
        value.get("error_signature") or failure.get("error_signature") or value.get("signature"),
        limit=2048,
    )
    normalized_error = _clean_text(
        value.get("normalized_error") or failure.get("normalized_error") or value.get("error") or failure.get("error") or error_signature,
        limit=8000,
    )
    changed_files = _normalize_changed_files(
        value.get("changed_files") or failure.get("changed_files") or value.get("files") or failure.get("files")
    )
    error_type = _clean_text(value.get("error_type") or failure.get("error_type"), limit=120)
    if not error_type:
        error_type = _infer_error_type(normalized_error, error_signature)
    module = _clean_text(value.get("module") or value.get("component") or failure.get("module"), limit=200)
    if not module:
        module = _infer_module(changed_files, normalized_error)
    return {
        "error_signature": error_signature,
        "normalized_error": normalized_error,
        "error_type": error_type or "unknown",
        "module": module or "unknown",
        "changed_files": changed_files,
    }


def _infer_error_type(normalized_error: str, error_signature: str) -> str:
    for candidate in (normalized_error, error_signature):
        match = _ERROR_TYPE_RE.search(candidate)
        if match:
            return match.group(1)
        prefix = candidate.split(":", 1)[0].strip()
        if prefix and len(prefix) <= 120 and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.-]*", prefix):
            return prefix
    return "unknown"


def _infer_module(changed_files: Sequence[str], normalized_error: str) -> str:
    match = _MODULE_RE.search(normalized_error)
    if match:
        return match.group(1).split(".", 1)[0]
    for filename in changed_files:
        parts = PurePosixPath(filename).parts
        if not parts:
            continue
        if parts[0] in {"tests", "test"} and len(parts) > 1:
            return parts[1].removesuffix(".py")
        return parts[0].removesuffix(".py")
    return "unknown"


def _normalize_changed_files(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        raw_items: Sequence[Any] = [value]
    elif isinstance(value, Mapping):
        raw_items = list(value.keys())
    elif isinstance(value, Sequence):
        raw_items = value
    else:
        raw_items = [value]
    files: list[str] = []
    for item in raw_items[:200]:
        if isinstance(item, Mapping):
            item = item.get("filename") or item.get("path") or ""
        path = _clean_text(item, limit=500).replace("\\", "/")
        if path.startswith("a/") or path.startswith("b/"):
            path = path[2:]
        path = path.lstrip("/")
        if not path or "\x00" in path or ".." in PurePosixPath(path).parts:
            continue
        if path not in files:
            files.append(path)
    return files


def _feature_vector(metadata: Mapping[str, Any], dimensions: int) -> dict[str, float]:
    text_parts = [
        str(metadata.get("error_signature") or ""),
        str(metadata.get("normalized_error") or ""),
        str(metadata.get("error_type") or ""),
        str(metadata.get("module") or ""),
        " ".join(str(item) for item in metadata.get("changed_files") or []),
    ]
    tokens = [token.lower() for token in _TOKEN_RE.findall(" ".join(text_parts))]
    features = tokens + [f"{left}::{right}" for left, right in zip(tokens, tokens[1:])]
    counts: dict[int, float] = {}
    for feature in features:
        digest = hashlib.blake2b(feature.encode("utf-8"), digest_size=8).digest()
        number = int.from_bytes(digest, "big", signed=False)
        index = number % dimensions
        sign = -1.0 if number & (1 << 63) else 1.0
        counts[index] = counts.get(index, 0.0) + sign
    norm = math.sqrt(sum(value * value for value in counts.values()))
    if norm <= 0:
        return {}
    return {str(index): round(value / norm, 10) for index, value in sorted(counts.items()) if value}


def _cosine(left: Mapping[str, Any], right: Mapping[str, Any]) -> float:
    if not left or not right:
        return 0.0
    left_values = {str(key): float(value) for key, value in left.items()}
    right_values = {str(key): float(value) for key, value in right.items()}
    dot = sum(value * right_values.get(key, 0.0) for key, value in left_values.items())
    left_norm = math.sqrt(sum(value * value for value in left_values.values()))
    right_norm = math.sqrt(sum(value * value for value in right_values.values()))
    if left_norm <= 0 or right_norm <= 0:
        return 0.0
    return dot / (left_norm * right_norm)


def _records_digest(records: Sequence[Mapping[str, Any]]) -> str:
    identity = [
        {
            "fix_id": str(record.get("fix_id") or ""),
            "decision_id": str(record.get("decision_id") or ""),
            "result_sha": str(record.get("result_sha") or ""),
            "patch_sha256": str(record.get("patch_sha256") or ""),
            "validation_sha256": str(record.get("validation_sha256") or ""),
            "recorded_at_ms": int(record.get("recorded_at_ms") or 0),
        }
        for record in sorted(records, key=lambda row: str(row.get("fix_id") or ""))
    ]
    return _digest(identity)


def _type_module_key(error_type: str, module: str) -> str:
    clean_type = _clean_text(error_type, limit=120).lower()
    clean_module = _clean_text(module, limit=200).lower()
    if not clean_type or not clean_module or clean_type == "unknown" or clean_module == "unknown":
        return ""
    return f"{clean_type}|{clean_module}"


def _previous_week_window(now_ms: int) -> tuple[int, int]:
    current = datetime.fromtimestamp(now_ms / 1000, tz=timezone.utc)
    current_week_start = datetime(current.year, current.month, current.day, tzinfo=timezone.utc) - timedelta(days=current.weekday())
    end_ms = int(current_week_start.timestamp() * 1000)
    start_ms = int((current_week_start - timedelta(days=7)).timestamp() * 1000)
    return start_ms, end_ms


def _process_findings(
    metrics: Mapping[str, Any],
    repeated_signatures: Sequence[Mapping[str, Any]],
    module_hotspots: Sequence[Mapping[str, Any]],
) -> list[str]:
    total = int(metrics.get("total_fixes") or 0)
    if total == 0:
        return ["No development-fix outcomes were recorded in the completed review week."]
    findings = [
        f"{int(metrics.get('successful_fixes') or 0)} of {total} fixes succeeded "
        f"({float(metrics.get('success_rate') or 0.0):.1%})."
    ]
    if repeated_signatures:
        findings.append(f"{len(repeated_signatures)} error signatures repeated during the week.")
    if module_hotspots:
        findings.append(f"Failure hotspots were detected in {len(module_hotspots)} modules.")
    missing = int(metrics.get("missing_search_metadata_count") or 0)
    if missing:
        findings.append(f"{missing} outcomes lacked complete similarity-search metadata.")
    return findings


def _process_recommendations(
    metrics: Mapping[str, Any],
    repeated_signatures: Sequence[Mapping[str, Any]],
    module_hotspots: Sequence[Mapping[str, Any]],
    failed_checks: Mapping[str, int],
) -> list[dict[str, Any]]:
    recommendations: list[dict[str, Any]] = []
    total = int(metrics.get("total_fixes") or 0)
    success_rate = float(metrics.get("success_rate") or 0.0)
    if total == 0:
        recommendations.append({
            "priority": "normal",
            "action": "enforce_fix_outcome_recording",
            "reason": "No weekly development evidence was available for process learning.",
        })
    elif success_rate < 0.7:
        recommendations.append({
            "priority": "high",
            "action": "strengthen_pre_apply_validation",
            "reason": f"Weekly fix success rate was {success_rate:.1%}, below the 70% process target.",
        })
    if repeated_signatures:
        recommendations.append({
            "priority": "high",
            "action": "promote_exact_few_shot_reuse",
            "reason": "Repeated error signatures should reuse validated fixes before generating new patches.",
            "error_signatures": [str(item.get("error_signature") or "") for item in repeated_signatures[:10]],
        })
    if module_hotspots:
        recommendations.append({
            "priority": "high",
            "action": "add_module_targeted_regressions",
            "reason": "Modules with repeated failed fixes need narrower deterministic regression tests.",
            "modules": [str(item.get("module") or "") for item in module_hotspots[:10]],
        })
    missing = int(metrics.get("missing_search_metadata_count") or 0)
    if missing:
        recommendations.append({
            "priority": "normal",
            "action": "require_structured_error_metadata",
            "reason": f"{missing} outcomes could not fully participate in exact and typed-module search.",
        })
    if failed_checks:
        recommendations.append({
            "priority": "high",
            "action": "prioritize_failed_validation_checks",
            "reason": "Frequently failing validation checks should run earlier in the repair pipeline.",
            "checks": [name for name, _count in Counter(failed_checks).most_common(10)],
        })
    if not recommendations:
        recommendations.append({
            "priority": "normal",
            "action": "preserve_process_and_refresh_memory",
            "reason": "The completed week did not reveal a material process regression.",
        })
    return recommendations


def _validation_timestamp(validation: Mapping[str, Any]) -> int:
    for key in ("completed_at_ms", "finished_at_ms", "validated_at_ms", "recorded_at_ms"):
        try:
            parsed = int(validation.get(key))
        except (TypeError, ValueError):
            continue
        if parsed > 0:
            return parsed * 1000 if parsed < 10_000_000_000 else parsed
    return 0


def _sanitize(value: Any, *, depth: int = 0) -> Any:
    if depth > 8:
        return "<truncated>"
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("validation contains a non-finite number")
        return value
    if isinstance(value, str):
        return value[:16_000]
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for index, (key, item) in enumerate(value.items()):
            if index >= 200:
                result["<truncated>"] = True
                break
            clean_key = _clean_text(key, limit=200) or "unknown"
            normalized_key = clean_key.lower().replace("-", "_")
            result[clean_key] = "<redacted>" if any(marker in normalized_key for marker in _SENSITIVE_MARKERS) else _sanitize(item, depth=depth + 1)
        return result
    if isinstance(value, Sequence):
        return [_sanitize(item, depth=depth + 1) for item in list(value)[:500]]
    return _clean_text(value, limit=2000)


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return []
    return [str(item) for item in value if str(item)]


def _clean_identifier(value: Any, name: str) -> str:
    text = _clean_text(value, limit=200)
    if not text or any(ord(character) < 32 for character in text):
        raise ValueError(f"{name} must be a non-empty printable identifier")
    return text


def _clean_text(value: Any, *, limit: int) -> str:
    return "" if value is None else str(value).strip()[:limit]


def _bounded_int(value: Any, *, minimum: int, maximum: int, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return min(max(parsed, minimum), maximum)


def _digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    ).hexdigest()


def _now_ms() -> int:
    return int(time.time() * 1000)


__all__ = ["DevelopmentLearningService"]
