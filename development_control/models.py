"""Typed contracts for bounded development changes proposed by AI agents."""
from __future__ import annotations

import hashlib
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

_SHA_RE = re.compile(r"^[0-9a-f]{7,64}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

DecisionKind = Literal[
    "proposal",
    "security_review",
    "approval",
    "application",
    "rollback",
    "learning",
]
DecisionStatus = Literal[
    "proposed",
    "under_review",
    "approved",
    "rejected",
    "applied",
    "failed",
    "rolled_back",
]
PatchSecurityVerdict = Literal["allow", "review", "deny"]
RiskLevel = Literal["low", "medium", "high", "critical"]


class PatchVerdict(BaseModel):
    """Security Guard result for one exact patch digest."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, frozen=True)

    verdict: PatchSecurityVerdict
    policy_version: str = Field(min_length=1, max_length=100)
    reasons: list[str] = Field(default_factory=list, max_length=100)
    protected_paths: list[str] = Field(default_factory=list, max_length=200)
    security_checks: dict[str, bool] = Field(default_factory=dict)
    reviewed_by: str = Field(min_length=1, max_length=200)
    reviewed_at_ms: int = Field(gt=0)

    @field_validator("reasons", "protected_paths")
    @classmethod
    def normalize_string_lists(cls, values: list[str]) -> list[str]:
        normalized: list[str] = []
        for value in values:
            clean = str(value).strip()
            if not clean:
                raise ValueError("list items must not be empty")
            if clean not in normalized:
                normalized.append(clean)
        return normalized


class CodeChangeProposal(BaseModel):
    """Immutable proposal for one unified-diff change against one Git base SHA."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    proposal_id: str = Field(min_length=1, max_length=200)
    fix_id: str | None = Field(default=None, min_length=1, max_length=200)
    error_signature: str = Field(min_length=1, max_length=1_000)
    title: str = Field(min_length=1, max_length=300)
    rationale: str = Field(min_length=1, max_length=8_000)
    patch: str = Field(min_length=1, max_length=500_000)
    base_sha: str
    patch_sha256: str
    touched_paths: list[str] = Field(min_length=1, max_length=500)
    source: str = Field(min_length=1, max_length=100)
    created_at_ms: int = Field(gt=0)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("proposal_id", "error_signature", "title", "rationale", "source")
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        clean = value.strip()
        if not clean:
            raise ValueError("text fields must not be empty")
        return clean

    @field_validator("fix_id")
    @classmethod
    def strip_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        clean = value.strip()
        if not clean:
            raise ValueError("fix_id must not be empty")
        return clean

    @field_validator("base_sha")
    @classmethod
    def validate_base_sha(cls, value: str) -> str:
        clean = value.strip().lower()
        if not _SHA_RE.fullmatch(clean):
            raise ValueError("base_sha must contain 7..64 lowercase hexadecimal characters")
        return clean

    @field_validator("patch_sha256")
    @classmethod
    def validate_patch_sha256(cls, value: str) -> str:
        clean = value.strip().lower()
        if not _SHA256_RE.fullmatch(clean):
            raise ValueError("patch_sha256 must contain 64 lowercase hexadecimal characters")
        return clean

    @field_validator("patch")
    @classmethod
    def validate_patch_format(cls, value: str) -> str:
        if not value.startswith("diff --git "):
            raise ValueError("patch must be a unified Git diff")
        return value

    @field_validator("touched_paths")
    @classmethod
    def validate_touched_paths(cls, values: list[str]) -> list[str]:
        normalized: list[str] = []
        for value in values:
            clean = str(value).strip().replace("\\", "/")
            if not clean or clean.startswith("/") or clean.startswith("~"):
                raise ValueError("touched paths must be repository-relative")
            parts = [part for part in clean.split("/") if part]
            if not parts or any(part in {".", ".."} for part in parts):
                raise ValueError("touched paths must not traverse outside the repository")
            clean = "/".join(parts)
            if clean not in normalized:
                normalized.append(clean)
        return normalized

    @model_validator(mode="after")
    def verify_patch_digest(self) -> "CodeChangeProposal":
        digest = hashlib.sha256(self.patch.encode("utf-8")).hexdigest()
        if digest != self.patch_sha256:
            raise ValueError("patch_sha256 does not match patch content")
        return self


class AgentDecision(BaseModel):
    """Persistent General Controller decision about one exact code proposal."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, frozen=True)

    decision_id: str = Field(min_length=1, max_length=200)
    fix_id: str | None = Field(default=None, min_length=1, max_length=200)
    kind: DecisionKind
    status: DecisionStatus
    base_sha: str
    patch_sha256: str
    security_verdict: PatchVerdict
    proposal: CodeChangeProposal
    actor: str = Field(min_length=1, max_length=200)
    risk_level: RiskLevel = "medium"
    requires_approval: bool = True
    created_at_ms: int = Field(gt=0)
    updated_at_ms: int = Field(gt=0)
    decided_at_ms: int | None = Field(default=None, gt=0)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("base_sha")
    @classmethod
    def validate_base_sha(cls, value: str) -> str:
        clean = value.lower()
        if not _SHA_RE.fullmatch(clean):
            raise ValueError("base_sha must contain 7..64 lowercase hexadecimal characters")
        return clean

    @field_validator("patch_sha256")
    @classmethod
    def validate_patch_sha256(cls, value: str) -> str:
        clean = value.lower()
        if not _SHA256_RE.fullmatch(clean):
            raise ValueError("patch_sha256 must contain 64 lowercase hexadecimal characters")
        return clean

    @model_validator(mode="after")
    def validate_consistency(self) -> "AgentDecision":
        if self.proposal.base_sha != self.base_sha:
            raise ValueError("decision base_sha must match proposal base_sha")
        if self.proposal.patch_sha256 != self.patch_sha256:
            raise ValueError("decision patch_sha256 must match proposal patch_sha256")
        if self.fix_id is not None and self.proposal.fix_id not in {None, self.fix_id}:
            raise ValueError("decision fix_id must match proposal fix_id")
        terminal = {"approved", "rejected", "applied", "failed", "rolled_back"}
        if self.status in terminal and self.decided_at_ms is None:
            raise ValueError("terminal decisions require decided_at_ms")
        if self.decided_at_ms is not None and self.decided_at_ms < self.created_at_ms:
            raise ValueError("decided_at_ms must not precede created_at_ms")
        if self.updated_at_ms < self.created_at_ms:
            raise ValueError("updated_at_ms must not precede created_at_ms")
        if self.security_verdict.verdict == "deny" and self.status in {"approved", "applied"}:
            raise ValueError("a denied patch cannot be approved or applied")
        if self.status == "applied" and self.security_verdict.verdict != "allow":
            raise ValueError("an applied patch requires an allow security verdict")
        return self


__all__ = [
    "AgentDecision",
    "CodeChangeProposal",
    "DecisionKind",
    "DecisionStatus",
    "PatchSecurityVerdict",
    "PatchVerdict",
    "RiskLevel",
]
