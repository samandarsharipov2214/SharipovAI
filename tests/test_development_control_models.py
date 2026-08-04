from __future__ import annotations

import hashlib

import pytest
from pydantic import ValidationError

from ai_architecture_registry import responsibility_owner
from development_control import AgentDecision, CodeChangeProposal, PatchVerdict, validate_patch


def _patch() -> str:
    return (
        "diff --git a/app/example.py b/app/example.py\n"
        "--- a/app/example.py\n"
        "+++ b/app/example.py\n"
        "@@ -1 +1 @@\n"
        "-VALUE = 1\n"
        "+VALUE = 2\n"
    )


def test_code_change_proposal_binds_patch_hash() -> None:
    patch = _patch()
    proposal = CodeChangeProposal(
        proposal_id="proposal-1",
        error_signature="ValueError:invalid-state",
        patch=patch,
        base_sha="1a2b3c4",
        source="self-healing-agent",
        affected_files=("app/example.py",),
        created_at_ms=1,
    )
    assert proposal.patch_sha256 == hashlib.sha256(patch.encode("utf-8")).hexdigest()
    assert proposal.affected_files == ("app/example.py",)


def test_code_change_proposal_rejects_hash_mismatch_and_unsafe_path() -> None:
    with pytest.raises(ValidationError, match="patch_sha256 does not match"):
        CodeChangeProposal(
            error_signature="error",
            patch=_patch(),
            base_sha="1a2b3c4",
            patch_sha256="0" * 64,
            source="agent",
        )
    with pytest.raises(ValidationError, match="unsafe repository path"):
        CodeChangeProposal(
            error_signature="error",
            patch=_patch(),
            base_sha="1a2b3c4",
            source="agent",
            affected_files=("../CONSTITUTION.md",),
        )


def test_denied_verdict_requires_reason() -> None:
    with pytest.raises(ValidationError, match="must include at least one reason"):
        PatchVerdict(allowed=False, created_at_ms=1)
    verdict = PatchVerdict(
        allowed=False,
        reasons=["protected path"],
        checked_paths=["CONSTITUTION.md"],
        created_at_ms=1,
    )
    assert verdict.allowed is False
    assert verdict.reasons == ["protected path"]


def test_agent_decision_cannot_approve_denied_patch() -> None:
    denied = PatchVerdict(allowed=False, reasons=["dangerous construct"], created_at_ms=1)
    with pytest.raises(ValidationError, match="cannot be approved or applied"):
        AgentDecision(
            decision_id="decision-1",
            fix_id="fix-1",
            kind="approval",
            status="approved",
            base_sha="1a2b3c4",
            patch_sha256="a" * 64,
            security_verdict=denied,
            actor="general_controller",
            created_at_ms=2,
            updated_at_ms=2,
        )


def test_security_guard_returns_shared_pydantic_verdict() -> None:
    verdict = validate_patch(_patch())
    assert isinstance(verdict, PatchVerdict)
    assert verdict.allowed is True
    assert verdict.checked_paths == ["app/example.py"]


def test_security_guard_returns_denial_for_unsafe_path_instead_of_raising() -> None:
    patch = (
        "diff --git a/../escape.py b/../escape.py\n"
        "--- a/../escape.py\n"
        "+++ b/../escape.py\n"
        "@@ -0,0 +1 @@\n"
        "+VALUE = 1\n"
    )
    verdict = validate_patch(patch)
    assert verdict.allowed is False
    assert verdict.checked_paths == ["../escape.py"]
    assert "unsafe path: ../escape.py" in verdict.reasons


def test_self_healing_capabilities_have_canonical_owners() -> None:
    expected = {
        "development_change_orchestration": "general_controller",
        "patch_policy": "security_guard",
        "protected_path_guard": "security_guard",
        "repair_memory": "learning_engine",
        "few_shot_curation": "learning_engine",
    }
    for capability, owner in expected.items():
        result = responsibility_owner(capability)
        assert [item["id"] for item in result["owners"]] == [owner]
        assert result["recommendation"] == "extend_existing"
