from __future__ import annotations

import hashlib

import pytest
from pydantic import ValidationError

from development_control import AgentDecision, CodeChangeProposal, PatchVerdict
from development_control.security_guard import validate_patch


def _proposal(**overrides):
    payload = {
        "error_signature": "RuntimeError: database is locked",
        "patch": "diff --git a/storage/project_database.py b/storage/project_database.py\n",
        "source": "self_healing_agent",
        "base_sha": "a" * 40,
        "target_branch": "main",
        "changed_paths": ("storage/project_database.py",),
        "rationale": "Bound the retry and preserve evidence.",
        "tests": ("pytest -q tests/test_agent_learning_schema.py",),
        "created_at_ms": 1,
    }
    payload.update(overrides)
    return CodeChangeProposal(**payload)


def test_code_change_proposal_is_strict_and_hashes_exact_patch() -> None:
    proposal = _proposal()
    assert proposal.patch_sha256 == hashlib.sha256(proposal.patch.encode("utf-8")).hexdigest()
    assert proposal.changed_paths == ("storage/project_database.py",)
    with pytest.raises(ValidationError):
        _proposal(unexpected=True)


@pytest.mark.parametrize(
    "unsafe_path",
    (
        "../secrets.env",
        "/etc/passwd",
        "./storage/project_database.py",
        r"storage\project_database.py",
        "storage/../secrets.env",
    ),
)
def test_code_change_proposal_rejects_paths_outside_repository(unsafe_path: str) -> None:
    with pytest.raises(ValidationError):
        _proposal(changed_paths=(unsafe_path,))


def test_code_change_proposal_rejects_duplicate_paths_and_nul_patch() -> None:
    with pytest.raises(ValidationError):
        _proposal(changed_paths=("a.py", "a.py"))
    with pytest.raises(ValidationError):
        _proposal(patch="diff\x00")


def test_patch_verdict_is_pydantic_and_preserves_security_guard_api() -> None:
    verdict = PatchVerdict(
        allowed=False,
        reasons=["Protected deployment path changed."],
        policy_version="development-v1",
        protected_paths=["deploy/vps/docker-compose.yml"],
        required_checks=["project-guardrails"],
        requires_human_approval=True,
        checked_at_ms=2,
    )
    assert verdict.allowed is False
    assert verdict.verdict == "manual_review"
    assert verdict.reasons == ["Protected deployment path changed."]

    protected = validate_patch(
        "diff --git a/Dockerfile b/Dockerfile\n"
        "--- a/Dockerfile\n"
        "+++ b/Dockerfile\n"
        "@@ -1 +1 @@\n"
        "-FROM python\n"
        "+FROM alpine\n"
    )
    assert protected.allowed is False
    assert protected.verdict == "manual_review"
    assert protected.protected_paths == ["Dockerfile"]

    with pytest.raises(ValidationError):
        PatchVerdict(allowed=False, reasons=[])
    with pytest.raises(ValidationError):
        PatchVerdict(
            allowed=True,
            requires_human_approval=True,
            protected_paths=["Dockerfile"],
        )


def test_agent_decision_requires_allow_before_approval_or_apply() -> None:
    patch_hash = "b" * 64
    decision = AgentDecision(
        decision_id="decision-1",
        fix_id="fix-1",
        kind="approve",
        status="approved",
        base_sha="a" * 40,
        target_branch="main",
        patch_sha256=patch_hash,
        security_verdict="allow",
        actor="security_guard",
        rationale="All checks passed.",
        created_at_ms=10,
        updated_at_ms=11,
    )
    assert decision.security_verdict == "allow"

    with pytest.raises(ValidationError):
        AgentDecision(
            kind="apply",
            status="applied",
            base_sha="a" * 40,
            target_branch="main",
            patch_sha256=patch_hash,
            security_verdict="manual_review",
            actor="general_controller",
            rationale="Unsafe bypass.",
        )


def test_agent_decision_rejects_invalid_hashes_timestamps_and_rollback_state() -> None:
    common = {
        "base_sha": "a" * 40,
        "target_branch": "main",
        "patch_sha256": "b" * 64,
        "security_verdict": "block",
        "actor": "security_guard",
        "rationale": "Blocked.",
    }
    with pytest.raises(ValidationError):
        AgentDecision(kind="reject", status="rejected", **{**common, "base_sha": "short"})
    with pytest.raises(ValidationError):
        AgentDecision(kind="reject", status="rejected", **{**common, "patch_sha256": "bad"})
    with pytest.raises(ValidationError):
        AgentDecision(
            kind="verify",
            status="rejected",
            created_at_ms=20,
            updated_at_ms=19,
            **common,
        )
    with pytest.raises(ValidationError):
        AgentDecision(kind="verify", status="rolled_back", **common)
