"""Authenticated internal persistence for self-healing action outcomes."""
from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Literal

from fastapi import FastAPI, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator

from storage import ProjectDatabase, VersionConflict

from .internal_service_auth import require_internal_service

_DECISION_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,169}$")
_SHA40 = re.compile(r"^[0-9a-f]{40}$")
_SHA64 = re.compile(r"^[0-9a-f]{64}$")


class AgentDecisionResult(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    decision_id: str
    action: Literal["apply_approved_patch"] = "apply_approved_patch"
    status: Literal["rejected", "failed_precommit", "applied", "reverted", "rollback_failed"]
    phase: str = Field(min_length=1, max_length=80)
    message: str = Field(min_length=1, max_length=4000)
    base_sha: str
    patch_sha256: str
    commit_sha: str = ""
    health_verified: bool = False

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

    @field_validator("commit_sha")
    @classmethod
    def validate_commit_sha(cls, value: str) -> str:
        normalized = value.lower()
        if normalized and not _SHA40.fullmatch(normalized):
            raise ValueError("commit_sha must be empty or a lowercase 40-character Git SHA")
        return normalized


def _canonical_payload(payload: AgentDecisionResult) -> dict[str, object]:
    return payload.model_dump(mode="json")


def install_internal_agent_decisions_api(app: FastAPI) -> None:
    if getattr(app.state, "internal_agent_decisions_api_installed", False):
        return
    app.state.internal_agent_decisions_api_installed = True

    @app.post("/internal/agent-decisions", include_in_schema=False)
    def record_agent_decision(
        payload: AgentDecisionResult,
        request: Request,
        response: Response,
    ) -> dict[str, object]:
        require_internal_service(request)
        database = ProjectDatabase()
        database.initialize()
        value = _canonical_payload(payload)
        existing = database.get_json("agent_decisions", payload.decision_id)
        if existing is not None:
            previous = existing.get("value")
            if isinstance(previous, dict) and {
                key: previous.get(key) for key in value
            } == value:
                response.headers["Cache-Control"] = "no-store"
                return {
                    "status": "ok",
                    "decision_id": payload.decision_id,
                    "version": int(existing["version"]),
                    "idempotent": True,
                }
            raise HTTPException(
                status_code=409,
                detail={"status": "agent_decision_conflict", "decision_id": payload.decision_id},
            )

        stored = {
            **value,
            "recorded_at": datetime.now(UTC).isoformat(),
            "source": "self-healing-run",
        }
        try:
            version = database.put_json(
                "agent_decisions",
                payload.decision_id,
                stored,
                expected_version=0,
            )
        except VersionConflict as exc:
            raise HTTPException(
                status_code=409,
                detail={"status": "agent_decision_conflict", "decision_id": payload.decision_id},
            ) from exc
        response.headers["Cache-Control"] = "no-store"
        return {
            "status": "ok",
            "decision_id": payload.decision_id,
            "version": version,
            "idempotent": False,
        }


__all__ = ["AgentDecisionResult", "install_internal_agent_decisions_api"]
