"""Typed development-control contracts for bounded autonomous code changes."""
from __future__ import annotations

import hashlib
import time
import uuid
from pathlib import PurePosixPath
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator, model_validator

DecisionKind = Literal[
    "propose",
    "security_review",
    "approve",
    "reject",
    "apply",
    "verify",
    "rollback",
]
DecisionStatus = Literal[
    "pending",
    "approved",
    "rejected",
    "applied",
    "failed",
    "rolled_back",
]
SecurityVerdict = Literal["not_evaluated", "allow", "block", "manual_review"]
Verdict = Literal["allow", "block", "manual_review"]


def _now_ms() -> int:
    return int(time.time() * 1000)


def _validate_repo_path(value: str) -> str:
    clean = str(value).strip()
    if not clean or len(clean) > 500:
        raise ValueError("repository path must contain 1..500 characters")
    if "\x00" in clean or "\\" in clean:
        raise ValueError("repository path must be a safe POSIX path")
    path = PurePosixPath(clean)
    if path.is_absolute() or clean.startswith("./") or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError("repository path must stay inside the repository")
    return path.as_posix()


def _clean_unique(values: tuple[str, ...], *, field_name: str, path_values: bool = False) -> tuple[str, ...]:
    cleaned: list[str] = []
    seen: set[str] = set()
    for value in values:
        item = _validate_repo_path(value) if path_values else str(value).strip()
        if not item:
            raise ValueError(f"{field_name} must not contain empty entries")
        if item in seen:
            raise ValueError(f"{field_name} must not contain duplicates")
        seen.add(item)
        cleaned.append(item)
    return tuple(cleaned)


class CodeChangeProposal(BaseModel):
    """Immutable proposal emitted before any repository mutation is authorized."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    proposal_id: str = Field(default_factory=lambda: str(uuid.uuid4()), min_length=1, max_length=200)
    error_signature: str = Field(min_length=1, max_length=2048)
    patch: str = Field(min_length=1, max_length=2_000_000)
    source: str = Field(min_length=1, max_length=100)
    base_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    target_branch: str = Field(min_length=1, max_length=200)
    changed_paths: tuple[str, ...] = Field(min_length=1, max_length=100)
    rationale: str = Field(min_length=1, max_length=20_000)
    tests: tuple[str, ...] = Field(default=(), max_length=100)
    created_at_ms: int = Field(default_factory=_now_ms, gt=0)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("error_signature", "source", "target_branch", "rationale")
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        clean = value.strip()
        if not clean:
            raise ValueError("value must not be blank")
        if "\x00" in clean:
            raise ValueError("value must not contain NUL bytes")
        return clean

    @field_validator("patch")
    @classmethod
    def validate_patch(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("patch must not be blank")
        if "\x00" in value:
            raise ValueError("patch must not contain NUL bytes")
        return value

    @field_validator("changed_paths")
    @classmethod
    def validate_changed_paths(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _clean_unique(value, field_name="changed_paths", path_values=True)

    @field_validator("tests")
    @classmethod
    def validate_tests(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _clean_unique(value, field_name="tests")

    @computed_field(return_type=str)
    @property
    def patch_sha256(self) -> str:
        return hashlib.sha256(self.patch.encode("utf-8")).hexdigest()


class PatchVerdict(BaseModel):
    """Security Guard result for a proposed patch and its protected paths."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    verdict: Verdict
    policy_version: str = Field(min_length=1, max_length=100)
    protected_paths: tuple[str, ...] = Field(default=(), max_length=100)
    findings: tuple[str, ...] = Field(default=(), max_length=200)
    required_checks: tuple[str, ...] = Field(default=(), max_length=100)
    requires_human_approval: bool = False
    checked_at_ms: int = Field(default_factory=_now_ms, gt=0)

    @field_validator("policy_version")
    @classmethod
    def validate_policy_version(cls, value: str) -> str:
        clean = value.strip()
        if not clean:
            raise ValueError("policy_version must not be blank")
        return clean

    @field_validator("protected_paths")
    @classmethod
    def validate_protected_paths(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _clean_unique(value, field_name="protected_paths", path_values=True)

    @field_validator("findings", "required_checks")
    @classmethod
    def validate_text_items(cls, value: tuple[str, ...], info) -> tuple[str, ...]:
        return _clean_unique(value, field_name=info.field_name)

    @model_validator(mode="after")
    def validate_verdict_contract(self) -> "PatchVerdict":
        if self.verdict in {"block", "manual_review"} and not self.findings:
            raise ValueError("blocked or manual-review verdicts require findings")
        if self.verdict == "manual_review" and not self.requires_human_approval:
            raise ValueError("manual_review requires human approval")
        if self.verdict == "allow" and self.requires_human_approval:
            raise ValueError("allow verdict cannot require human approval")
        return self


class AgentDecision(BaseModel):
    """Append-only decision record binding a patch to security and Git evidence."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    decision_id: str = Field(default_factory=lambda: str(uuid.uuid4()), min_length=1, max_length=200)
    fix_id: str | None = Field(default=None, min_length=1, max_length=200)
    kind: DecisionKind
    status: DecisionStatus
    base_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    target_branch: str = Field(min_length=1, max_length=200)
    patch_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    security_verdict: SecurityVerdict = "not_evaluated"
    actor: str = Field(min_length=1, max_length=200)
    rationale: str = Field(min_length=1, max_length=20_000)
    created_at_ms: int = Field(default_factory=_now_ms, gt=0)
    updated_at_ms: int = Field(default_factory=_now_ms, gt=0)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("fix_id", "target_branch", "actor", "rationale")
    @classmethod
    def strip_optional_or_required_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        clean = value.strip()
        if not clean:
            raise ValueError("value must not be blank")
        if "\x00" in clean:
            raise ValueError("value must not contain NUL bytes")
        return clean

    @model_validator(mode="after")
    def validate_decision_contract(self) -> "AgentDecision":
        if self.updated_at_ms < self.created_at_ms:
            raise ValueError("updated_at_ms must not precede created_at_ms")
        if self.status in {"approved", "applied"} and self.security_verdict != "allow":
            raise ValueError("approved or applied decisions require an allow security verdict")
        if self.status == "rolled_back" and self.kind != "rollback":
            raise ValueError("rolled_back status requires rollback kind")
        return self


__all__ = [
    "AgentDecision",
    "CodeChangeProposal",
    "DecisionKind",
    "DecisionStatus",
    "PatchVerdict",
    "SecurityVerdict",
    "Verdict",
]
