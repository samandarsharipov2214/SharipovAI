"""Bridge from the Self-Healing Agent to owner-gated development control."""
from __future__ import annotations

from typing import Any, Mapping

from .general_controller import AgentDecision, DevelopmentChangeController


def route_successful_ai_fix(
    agent: Any,
    *,
    head: str,
    output: str,
    command: Any,
) -> AgentDecision | None:
    """Ask the configured AI fixer for a proposal and route it for approval.

    Returns ``None`` when no fixer is configured or when the attempt did not
    produce a successful unified-diff proposal. This function never writes the
    repository and never queues host application by itself.
    """
    fixer = getattr(agent, "ai_fixer", None)
    attempt = getattr(fixer, "attempt", None)
    if not callable(attempt):
        return None

    result = attempt(head=head, output=output, command=command)
    proposal = _successful_proposal(result, head=head, output=output, command=command)
    if proposal is None:
        return None

    controller = getattr(agent, "development_controller", None)
    if controller is None:
        controller = DevelopmentChangeController()
        agent.development_controller = controller
    decision = controller.submit_proposal(proposal)
    decision = controller.security_review(decision.decision_id)
    if decision.security_verdict.get("allowed") is True:
        decision = controller.request_owner_approval(decision.decision_id)
    return decision


def _successful_proposal(result: Any, *, head: str, output: str, command: Any) -> dict[str, Any] | None:
    if result is None or result is False:
        return None
    if isinstance(result, Mapping):
        payload = dict(result)
    else:
        payload = {
            key: getattr(result, key)
            for key in ("success", "status", "patch", "changed_files", "files", "tests", "test_results", "error")
            if hasattr(result, key)
        }
    success = payload.get("success") is True or str(payload.get("status", "")).lower() in {
        "success", "fixed", "proposal_ready", "ready",
    }
    patch = payload.get("patch")
    if not success or not isinstance(patch, str) or not patch.strip():
        return None
    files = payload.get("changed_files") or payload.get("files") or []
    if not isinstance(files, list):
        files = []
    return {
        "error": str(payload.get("error") or output[-3000:]),
        "patch": patch,
        "changed_files": [str(item) for item in files],
        "test_results": payload.get("test_results") or payload.get("tests") or "AI fixer reported success; host must re-run tests before application",
        "source_head": str(head),
        "verification_command": command,
        "source": "self_healing_agent.ai_fixer",
    }


__all__ = ["route_successful_ai_fix"]
