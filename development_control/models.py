"""Typed contracts for bounded AI-assisted code changes."""
from __future__ import annotations

import hashlib
import re
import time
import uuid
from pathlib import PurePosixPath
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

_SHA_RE = re.compile(r"^[0-9a-f]{7,64}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

DecisionKind = Literal["proposal", "security_review", "approval", "application", "rollback", "learning"]
DecisionStatus = Literal["pending", "approved", "rejected", "applied", "failed", "rolled_back"]


def _now_ms() -> int:
    return int(time.time() * 1000)


def _identifier(value: str, field_name: str) -> str:
    clean = str(value).strip()
    if not clean or len(clean) > 200:
        raise ValueError(f"{field_name} must contain 1..200 characters")
    return clean


def _safe_path(value: str) -> str:
    clean = str(value).strip().replace("\\", "/")
    path = PurePosixPath(clean)
    if not clean or path.is_absolute() or ".." in path.parts or clean.startswith("./"):
        raise ValueError(f"unsafe repository path: {value}")
    return clean


class PatchVerdict(BaseModel):
    """Fail-closed security verdict for one patch."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    allowed: bool
    reasons: tuple[str, ...] = ()
    checked_paths: tuple[str, ...] = ()
    policy_version: str = Field(default="1", min_length=1, max_length=64)
    created_at_ms: int = Field(default_factory=_now_ms, gt=0)

    @field_validator("reasons")
    @classmethod
    def _normalize_reasons(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(_identifier(item, "reason") for item in value)

    @field_validator("checked_paths")
    @classmethod
    def _normalize_paths(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(_safe_path(item) for item in value)

    @model_validator(mode="after")
    def _denial_requires_reason(self) -> "PatchVerdict":
        if not self.allowed and not self.reasons:
            raise ValueError("a denied patch verdict must include at least one reason")
        return self


class CodeChangeProposal(BaseModel):
    """Immutable proposal submitted to the development-control pipeline."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    proposal_id: str = Field(default_factory=lambda: str(uuid.uuid4()), min_length=1, max_length=200)
    error_signature: str = Field(min_length=1, max_length=4000)
    patch: str = Field(min_length=1, max_length=2_000_000)
    base_sha: str
    patch_sha256: str = ""
    source: str = Field(min_length=1, max_length=200)
    rationale: str = Field(default="", max_length=20_000)
    affected_files: tuple[str, ...] = ()
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at_ms: int = Field(default_factory=_now_ms, gt=0)

    @field_validator("proposal_id", "source")
    @classmethod
    def _normalize_identifiers(cls, value: str, info: Any) -> str:
        return _identifier(value, info.field_name)

    @field_validator("base_sha")
    @classmethod
    def _validate_base_sha(cls, value: str) -> str:
        clean = str(value).strip().lower()
        if not _SHA_RE.fullmatch(clean):
            raise ValueError("base_sha must be a 7..64 character hexadecimal Git SHA")
        return clean

    @field_validator("affected_files")
    @classmethod
    def _validate_affected_files(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(_safe_path(item) for item in value)
        if len(set(normalized)) != len(normalized):
            raise ValueError("affected_files must be unique")
        return normalized

    @field_validator("patch")
    @classmethod
    def _validate_patch(cls, value: str) -> str:
        if not value.strip().startswith("diff --git "):
            raise ValueError("patch must be a unified git diff")
        return value

    @model_validator(mode="after")
    def _bind_patch_hash(self) -> "CodeChangeProposal":
        digest = hashlib.sha256(self.patch.encode("utf-8")).hexdigest()
        if self.patch_sha256 and self.patch_sha256.lower() != digest:
            raise ValueError("patch_sha256 does not match patch content")
        object.__setattr__(self, "patch_sha256", digest)
        return self


class AgentDecision(BaseModel):
    """Immutable decision record linked to one proposed fix."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    decision_id: str = Field(default_factory=lambda: str(uuid.uuid4()), min_length=1, max_length=200)
    fix_id: str = Field(min_length=1, max_length=200)
    kind: DecisionKind
    status: DecisionStatus = "pending"
    base_sha: str
    patch_sha256: str
    security_verdict: PatchVerdict
    actor: str = Field(min_length=1, max_length=200)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at_ms: int = Field(default_factory=_now_ms, gt=0)
    updated_at_ms: int = Field(default_factory=_now_ms, gt=0)

    @field_validator("decision_id", "fix_id", "actor")
    @classmethod
    def _normalize_identifiers(cls, value: str, info: Any) -> str:
        return _identifier(value, info.field_name)

    @field_validator("base_sha")
    @classmethod
    def _validate_base_sha(cls, value: str) -> str:
        clean = str(value).strip().lower()
        if not _SHA_RE.fullmatch(clean):
            raise ValueError("base_sha must be a 7..64 character hexadecimal Git SHA")
        return clean

    @field_validator("patch_sha256")
    @classmethod
    def _validate_patch_sha256(cls, value: str) -> str:
        clean = str(value).strip().lower()
        if not _SHA256_RE.fullmatch(clean):
            raise ValueError("patch_sha256 must be a lowercase SHA-256 digest")
        return clean

    @model_validator(mode="after")
    def _validate_state(self) -> "AgentDecision":
        if self.updated_at_ms < self.created_at_ms:
            raise ValueError("updated_at_ms cannot be earlier than created_at_ms")
        if self.status in {"approved", "applied"} and not self.security_verdict.allowed:
            raise ValueError("a denied patch cannot be approved or applied")
        if self.kind == "rollback" and self.status == "applied":
            raise ValueError("rollback decisions must use rolled_back status")
        return self


__all__ = [
    "AgentDecision",
    "CodeChangeProposal",
    "DecisionKind",
    "DecisionStatus",
    "PatchVerdict",
]
