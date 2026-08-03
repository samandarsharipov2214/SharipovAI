from __future__ import annotations

import hashlib

import pytest
from pydantic import ValidationError

from development_control import AgentDecision, CodeChangeProposal, PatchVerdict

PATCH = """diff --git a/example.py b/example.py
--- a/example.py
+++ b/example.py
@@ -1 +1 @@
-old = True
+old = False
"""
PATCH_SHA = hashlib.sha256(PATCH.encode("utf-8")).hexdigest()
BASE_SHA = "a" * 40


def _proposal(**overrides: object) -> CodeChangeProposal:
    payload: dict[str, object] = {
        "proposal_id": "proposal-1",
        "fix_id": "fix-1",
        "error_signature": "ValueError: deterministic failure",
        "title": "Fix deterministic failure",
        "rationale": "The patch changes the smallest failing line and keeps existing safety contracts.",
        "patch": PATCH,
        "base_sha": BASE_SHA,
        "patch_sha256": PATCH_SHA,
        "touched_paths": ["example.py"],
        "source": "self_healing_agent",
        "created_at_ms": 100,
        "metadata": {"test": True},
    }
    payload.update(overrides)
    return CodeChangeProposal.model_validate(payload)


def _verdict(**overrides: object) -> PatchVerdict:
    payload: dict[str, object] = {
        "verdict": "allow",
        "policy_version": "patch-policy-v1",
        "reasons": ["focused patch", "no protected paths"],
        "protected_paths": [],
        "security_checks": {"secret_scan": True, "protected_path_guard": True},
        "reviewed_by": "security_guard",
        "reviewed_at_ms": 110,
    }
    payload.update(overrides)
    return PatchVerdict.model_validate(payload)


def test_code_change_proposal_verifies_digest_and_paths() -> None:
    proposal = _proposal(touched_paths=["example.py", "example.py"])
    assert proposal.patch_sha256 == PATCH_SHA
    assert proposal.touched_paths == ["example.py"]
    assert proposal.model_dump()["source"] == "self_healing_agent"
    with pytest.raises(ValidationError, match="does not match"):
        _proposal(patch_sha256="0" * 64)
    with pytest.raises(ValidationError, match="repository-relative"):
        _proposal(touched_paths=["/etc/passwd"])
    with pytest.raises(ValidationError, match="traverse"):
        _proposal(touched_paths=["../outside.py"])


def test_patch_verdict_is_strict_and_deduplicates_lists() -> None:
    verdict = _verdict(reasons=["safe", "safe"], protected_paths=["deploy/", "deploy/"])
    assert verdict.reasons == ["safe"]
    assert verdict.protected_paths == ["deploy/"]
    with pytest.raises(ValidationError):
        PatchVerdict.model_validate({**verdict.model_dump(), "unexpected": True})


def test_agent_decision_requires_matching_evidence_and_security_allow() -> None:
    proposal = _proposal()
    decision = AgentDecision.model_validate(
        {
            "decision_id": "decision-1",
            "fix_id": "fix-1",
            "kind": "application",
            "status": "applied",
            "base_sha": BASE_SHA,
            "patch_sha256": PATCH_SHA,
            "security_verdict": _verdict(),
            "proposal": proposal,
            "actor": "general_controller",
            "risk_level": "low",
            "requires_approval": True,
            "created_at_ms": 100,
            "updated_at_ms": 120,
            "decided_at_ms": 120,
        }
    )
    assert decision.status == "applied"
    assert decision.security_verdict.verdict == "allow"
    with pytest.raises(ValidationError, match="denied patch"):
        AgentDecision.model_validate(
            {
                **decision.model_dump(),
                "status": "approved",
                "security_verdict": _verdict(verdict="deny"),
            }
        )
    with pytest.raises(ValidationError, match="must match proposal"):
        AgentDecision.model_validate({**decision.model_dump(), "base_sha": "b" * 40})
    with pytest.raises(ValidationError, match="require decided_at_ms"):
        AgentDecision.model_validate(
            {**decision.model_dump(), "status": "failed", "decided_at_ms": None}
        )
