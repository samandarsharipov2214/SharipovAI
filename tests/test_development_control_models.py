from __future__ import annotations

import hashlib

import pytest
from pydantic import ValidationError

from ai_architecture_registry import responsibility_owner
from development_control import AgentDecision, CodeChangeProposal, PatchVerdict

_PATCH = """diff --git a/example.py b/example.py
--- a/example.py
+++ b/example.py
@@ -1 +1 @@
-old = 1
+new = 1
"""


def test_code_change_proposal_is_immutable_and_hashes_patch() -> None:
    proposal = CodeChangeProposal(
        proposal_id="proposal-1",
        title="Repair deterministic failure",
        description="Apply the smallest verified code change.",
        base_sha="ABCDEF1",
        patch=_PATCH,
        requested_by="self-healing-agent",
        source="self_healing_agent",
        created_at_ms=1000,
    )

    assert proposal.base_sha == "abcdef1"
    assert proposal.patch_sha256 == hashlib.sha256(_PATCH.encode("utf-8")).hexdigest()
    with pytest.raises(ValidationError):
        CodeChangeProposal(
            proposal_id="proposal-2",
            title="Bad patch",
            description="Not a unified diff.",
            base_sha="abcdef1",
            patch="print('not a diff')",
            requested_by="agent",
            source="self_healing_agent",
        )


def test_patch_verdict_is_fail_closed() -> None:
    allowed = PatchVerdict(
        allowed=True,
        checked_files=["example.py", "example.py"],
        risk_level="low",
    )
    assert allowed.checked_files == ["example.py"]

    denied = PatchVerdict(
        allowed=False,
        reasons=["protected path"],
        checked_files=["CONSTITUTION.md"],
        risk_level="critical",
    )
    assert denied.allowed is False

    with pytest.raises(ValidationError):
        PatchVerdict(allowed=False, reasons=[])
    with pytest.raises(ValidationError):
        PatchVerdict(allowed=True, reasons=["contradiction"])


def test_agent_decision_cannot_approve_denied_patch() -> None:
    verdict = PatchVerdict(
        allowed=False,
        reasons=["dangerous construct"],
        risk_level="critical",
    )
    with pytest.raises(ValidationError):
        AgentDecision(
            decision_id="decision-1",
            proposal_id="proposal-1",
            kind="apply",
            status="approved",
            base_sha="abcdef1",
            patch_sha256="a" * 64,
            security_verdict=verdict,
            actor="general-controller",
            created_at_ms=1000,
            updated_at_ms=1000,
        )

    blocked = AgentDecision(
        decision_id="decision-2",
        proposal_id="proposal-1",
        kind="reject",
        status="security_blocked",
        base_sha="abcdef1",
        patch_sha256="a" * 64,
        security_verdict=verdict,
        actor="security-guard",
        created_at_ms=1000,
        updated_at_ms=1001,
    )
    assert blocked.status == "security_blocked"


def test_new_capabilities_have_single_canonical_owner() -> None:
    expected = {
        "development_change_orchestration": "general_controller",
        "patch_policy": "security_guard",
        "protected_path_guard": "security_guard",
        "repair_memory": "learning_engine",
        "few_shot_curation": "learning_engine",
    }
    for capability, owner in expected.items():
        result = responsibility_owner(capability)
        assert result["status"] == "ok"
        assert result["owners"] == [
            {
                "id": owner,
                "name": next(item["name"] for item in result["owners"] if item["id"] == owner),
            }
        ]
