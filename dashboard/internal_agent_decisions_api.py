"""Authenticated internal validation and persistence for self-healing outcomes."""
from __future__ import annotations

import hashlib
import json
import re
import time
from typing import Literal

from fastapi import FastAPI, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from storage import ProjectDatabase, VersionConflict

from .internal_service_auth import require_internal_service

_DECISION_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,169}$")
_SHA40 = re.compile(r"^[0-9a-f]{40}$")
_SHA64 = re.compile(r"^[0-9a-f]{64}$")


class AgentDecisionClaim(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    decision_id: str
    action: Literal["apply_approved_patch"] = "apply_approved_patch"
    base_sha: str
    patch_sha256: str

    @field_validator("decision_id")
    @classmethod
    def validate_decision_id(cls, value: str) -> str:
        if not _DECISION_ID.fullmatch(value):
            raise ValueError("decision_id contains unsupported characters")
        return value

    @field_validator("base_sha")
    @classmethod
    def validate_base_sha(cls, value: str) -> str:
        normalized = value.lower()
        if not _SHA40.fullmatch(normalized):
            raise ValueError("base_sha must be a lowercase 40-character Git SHA")
        return normalized

    @field_validator("patch_sha256")
    @classmethod
    def validate_patch_sha(cls, value: str) -> str:
        normalized = value.lower()
        if not _SHA64.fullmatch(normalized):
            raise ValueError("patch_sha256 must be lowercase SHA-256")
        return normalized


class AgentDecisionResult(AgentDecisionClaim):
    status: Literal["rejected", "failed_precommit", "applied", "reverted", "rollback_failed"]
    phase: str = Field(min_length=1, max_length=80)
    message: str = Field(min_length=1, max_length=4000)
    commit_sha: str = ""
    health_verified: bool = False

    @field_validator("commit_sha")
    @classmethod
    def validate_commit_sha(cls, value: str) -> str:
        normalized = value.lower()
        if normalized and not _SHA40.fullmatch(normalized):
            raise ValueError("commit_sha must be empty or a lowercase 40-character Git SHA")
        return normalized

    @model_validator(mode="after")
    def validate_terminal_evidence(self) -> "AgentDecisionResult":
        if self.status == "applied" and (not self.commit_sha or not self.health_verified):
            raise ValueError("applied status requires commit_sha and verified health")
        if self.status == "reverted" and not self.commit_sha:
            raise ValueError("reverted status requires the reverted commit_sha")
        return self


def _database() -> ProjectDatabase:
    database = ProjectDatabase()
    database.initialize()
    return database


def _matching_decision(
    database: ProjectDatabase,
    claim: AgentDecisionClaim,
    *,
    require_approved: bool,
) -> dict[str, object]:
    decision = database.get_agent_decision(claim.decision_id)
    if decision is None:
        raise HTTPException(
            status_code=404,
            detail={"status": "agent_decision_not_found", "decision_id": claim.decision_id},
        )
    if decision["base_sha"] != claim.base_sha or decision["patch_sha256"] != claim.patch_sha256:
        raise HTTPException(
            status_code=409,
            detail={"status": "agent_decision_evidence_mismatch", "decision_id": claim.decision_id},
        )
    if require_approved and (decision["status"] != "approved" or decision["security_verdict"] != "allow"):
        raise HTTPException(
            status_code=409,
            detail={"status": "agent_decision_not_approved", "decision_id": claim.decision_id},
        )
    return decision


def _update_agent_decision_result(
    database: ProjectDatabase,
    *,
    decision_id: str,
    base_sha: str,
    patch_sha256: str,
    db_status: str,
    payload: dict[str, object],
    event_id: str,
    event_type: str,
    rationale: str,
) -> bool:
    terminal = {"applied", "failed", "rejected", "rolled_back"}
    now = int(time.time() * 1000)
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    with database.connect() as connection:
        try:
            database._begin(connection, immediate=True)  # noqa: SLF001 - canonical transactional adapter
            row = database._fetchone(  # noqa: SLF001
                connection,
                """
                SELECT status, base_sha, patch_sha256, security_verdict, metadata_json
                FROM agent_decisions WHERE decision_id = ?
                """,
                (decision_id,),
                lock=True,
            )
            if row is None:
                raise KeyError(f"agent decision not found: {decision_id}")
            if row["base_sha"] != base_sha or row["patch_sha256"] != patch_sha256:
                raise VersionConflict("agent decision evidence does not match manifest")
            current_metadata = json.loads(row["metadata_json"])
            current_result = current_metadata.get("host_result") if isinstance(current_metadata, dict) else None
            if row["status"] in terminal:
                if row["status"] == db_status and current_result == payload:
                    connection.rollback()
                    return True
                raise VersionConflict(f"agent decision is already terminal: {row['status']}")
            if row["status"] != "approved" or row["security_verdict"] != "allow":
                raise VersionConflict("agent decision is not owner/security approved")
            merged = dict(current_metadata) if isinstance(current_metadata, dict) else {}
            merged["host_result"] = payload
            database._execute(  # noqa: SLF001
                connection,
                """
                UPDATE agent_decisions
                SET status = ?, actor = ?, rationale = ?, metadata_json = ?, updated_at_ms = ?
                WHERE decision_id = ?
                """,
                (
                    db_status,
                    "self-healing-run",
                    rationale,
                    json.dumps(merged, ensure_ascii=False, separators=(",", ":"), sort_keys=True),
                    now,
                    decision_id,
                ),
            )
            database._execute(  # noqa: SLF001
                connection,
                """
                INSERT INTO agent_decision_events(
                    event_id, decision_id, event_type, actor, payload_json, created_at_ms
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (event_id, decision_id, event_type, "self-healing-run", encoded, now),
            )
            connection.commit()
            return False
        except Exception:
            connection.rollback()
            raise


def install_internal_agent_decisions_api(app: FastAPI) -> None:
    if getattr(app.state, "internal_agent_decisions_api_installed", False):
        return
    app.state.internal_agent_decisions_api_installed = True

    @app.post("/internal/agent-decisions/claim", include_in_schema=False)
    def claim_agent_decision(
        payload: AgentDecisionClaim,
        request: Request,
        response: Response,
    ) -> dict[str, object]:
        require_internal_service(request)
        decision = _matching_decision(_database(), payload, require_approved=True)
        response.headers["Cache-Control"] = "no-store"
        return {
            "status": "ok",
            "decision_id": payload.decision_id,
            "target_branch": decision["target_branch"],
            "approved": True,
        }

    @app.post("/internal/agent-decisions", include_in_schema=False)
    def record_agent_decision_result(
        payload: AgentDecisionResult,
        request: Request,
        response: Response,
    ) -> dict[str, object]:
        require_internal_service(request)
        database = _database()
        _matching_decision(database, payload, require_approved=False)
        db_status = {
            "rejected": "rejected",
            "failed_precommit": "failed",
            "applied": "applied",
            "reverted": "failed",
            "rollback_failed": "failed",
        }[payload.status]
        result = {
            **payload.model_dump(mode="json"),
            "source": "self-healing-run",
        }
        event_material = "\0".join(
            (payload.decision_id, payload.status, payload.phase, payload.commit_sha, payload.patch_sha256)
        )
        event_id = hashlib.sha256(event_material.encode("utf-8")).hexdigest()
        try:
            idempotent = _update_agent_decision_result(
                database,
                decision_id=payload.decision_id,
                base_sha=payload.base_sha,
                patch_sha256=payload.patch_sha256,
                db_status=db_status,
                payload=result,
                event_id=event_id,
                event_type=f"host_{payload.status}",
                rationale=payload.message,
            )
        except KeyError as exc:
            raise HTTPException(
                status_code=404,
                detail={"status": "agent_decision_not_found", "decision_id": payload.decision_id},
            ) from exc
        except VersionConflict as exc:
            raise HTTPException(
                status_code=409,
                detail={"status": "agent_decision_conflict", "decision_id": payload.decision_id},
            ) from exc
        response.headers["Cache-Control"] = "no-store"
        return {
            "status": "ok",
            "decision_id": payload.decision_id,
            "idempotent": idempotent,
        }


__all__ = ["AgentDecisionClaim", "AgentDecisionResult", "install_internal_agent_decisions_api"]
