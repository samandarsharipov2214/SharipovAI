"""Validated data contracts for bounded autonomous code changes."""
from __future__ import annotations

import hashlib
import re
import time
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

_SHA_RE = re.compile(r"^[0-9a-f]{7,64}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,200}$")


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class PatchVerdict(_StrictModel):
    """Fail-closed result produced by Security Guard patch validation."""

    allowed: bool
    reasons: list[str] = Field(default_factory=list, max_length=200)
    checked_files: list[str] = Field(default_factory=list, max_length=500)
    risk_level: Literal["low", "medium", "high", "critical"] = "low"

    @field_validator("reasons", "checked_files")
    @classmethod
    def _clean_text_items(cls, values: list[str]) -> list[str]:
        result: list[str] = []
        for value in values:
            clean = str(value).strip()
            if not clean:
                raise ValueError("list items must not be empty")
            if clean not in result:
                result.append(clean)
        return result

    @model_validator(mode="after")
    def _fail_closed_consistency(self) -> "PatchVerdict":
        if self.allowed and self.reasons:
            raise ValueError("allowed verdict cannot contain blocking reasons")
        if not self.allowed and not self.reasons:
            raise ValueError("denied verdict requires at least one reason")
        if self.risk_level == "critical" and self.allowed:
            raise ValueError("critical-risk patch cannot be allowed")
        return self


class CodeChangeProposal(_StrictModel):
    """Immutable proposal submitted to the development-change orchestrator."""

    proposal_id: str
    title: str = Field(min_length=3, max_length=200)
    description: str = Field(min_length=1, max_length=10_000)
    base_sha: str
    patch: str = Field(min_length=1, max_length=2_000_000)
    requested_by: str
    source: Literal["self_healing_agent", "operator", "ci", "learning_engine"]
    created_at_ms: int = Field(default_factory=lambda: int(time.time() * 1000), gt=0)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("proposal_id", "requested_by")
    @classmethod
    def _identifier(cls, value: str) -> str:
        clean = value.strip()
        if not _IDENTIFIER_RE.fullmatch(clean):
            raise ValueError("identifier contains unsafe characters")
        return clean

    @field_validator("base_sha")
    @classmethod
    def _base_sha(cls, value: str) -> str:
        clean = value.strip().lower()
        if not _SHA_RE.fullmatch(clean):
            raise ValueError("base_sha must be a 7..64 character hexadecimal Git SHA")
        return clean

    @field_validator("patch")
    @classmethod
    def _unified_diff(cls, value: str) -> str:
        if "\x00" in value:
            raise ValueError("patch must not contain NUL bytes")
        if not value.lstrip().startswith("diff --git "):
            raise ValueError("patch must be a unified git diff")
        return value

    @property
    def patch_sha256(self) -> str:
        return hashlib.sha256(self.patch.encode("utf-8")).hexdigest()


class AgentDecision(_StrictModel):
    """Persistent decision over one proposed or learned repair."""

    decision_id: str
    proposal_id: str
    fix_id: str | None = None
    kind: Literal["propose", "review", "apply", "reject", "rollback", "learn"]
    status: Literal[
        "pending",
        "security_blocked",
        "approved",
        "applied",
        "failed",
        "rolled_back",
        "learned",
    ]
    base_sha: str
    patch_sha256: str
    security_verdict: PatchVerdict
    actor: str
    created_at_ms: int = Field(default_factory=lambda: int(time.time() * 1000), gt=0)
    updated_at_ms: int = Field(default_factory=lambda: int(time.time() * 1000), gt=0)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("decision_id", "proposal_id", "actor", "fix_id")
    @classmethod
    def _optional_identifier(cls, value: str | None) -> str | None:
        if value is None:
            return None
        clean = value.strip()
        if not _IDENTIFIER_RE.fullmatch(clean):
            raise ValueError("identifier contains unsafe characters")
        return clean

    @field_validator("base_sha")
    @classmethod
    def _decision_base_sha(cls, value: str) -> str:
        clean = value.strip().lower()
        if not _SHA_RE.fullmatch(clean):
            raise ValueError("base_sha must be a 7..64 character hexadecimal Git SHA")
        return clean

    @field_validator("patch_sha256")
    @classmethod
    def _patch_sha256(cls, value: str) -> str:
        clean = value.strip().lower()
        if not _SHA256_RE.fullmatch(clean):
            raise ValueError("patch_sha256 must be a 64 character hexadecimal SHA-256")
        return clean

    @model_validator(mode="after")
    def _decision_matches_security(self) -> "AgentDecision":
        if self.status in {"approved", "applied", "learned"} and not self.security_verdict.allowed:
            raise ValueError("blocked patch cannot enter an approved state")
        if self.status == "security_blocked" and self.security_verdict.allowed:
            raise ValueError("security_blocked status requires a denied verdict")
        if self.updated_at_ms < self.created_at_ms:
            raise ValueError("updated_at_ms cannot precede created_at_ms")
        return self


__all__ = ["AgentDecision", "CodeChangeProposal", "PatchVerdict"]
