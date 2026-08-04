"""Bridge from the Self-Healing Agent to owner-gated development control."""
from __future__ import annotations

from typing import Any, Mapping

from .general_controller import DevelopmentChangeController, DevelopmentDecision


def route_successful_ai_fix(
    agent: Any,
    *,
    head: str,
    output: str,
    command: Any,
) -> DevelopmentDecision | None:
    """Route a successful AI-fixer candidate through governance.

    The bridge never mutates the repository and never queues host application.
    It stops after Security Guard review and an owner-approval request.
    """
    fixer = getattr(agent, "ai_fixer", None)
    attempt = getattr(fixer, "attempt", None)
    if not callable(attempt):
        return None

    try:
        result = attempt(head=head, output=output, command=command)
    except TypeError:
        # Current AIFixer accepts a FailureCase object; legacy integrations used
        # keyword arguments. Keep the bridge compatible without weakening checks.
        from tools.ai_fixer import FailureCase

        result = attempt(
            FailureCase(
                message=str(output),
                targeted_tests=list(command) if isinstance(command, (list, tuple)) else [],
            )
        )
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


def _successful_proposal(
    result: Any,
    *,
    head: str,
    output: str,
    command: Any,
) -> dict[str, Any] | None:
    if result is None or result is False:
        return None
    if isinstance(result, Mapping):
        payload = dict(result)
    else:
        payload = {
            key: getattr(result, key)
            for key in (
                "accepted",
                "success",
                "status",
                "patch",
                "changed_files",
                "files",
                "tests",
                "test_output",
                "test_results",
                "reasons",
                "error",
                "source",
            )
            if hasattr(result, key)
        }
    success = payload.get("accepted") is True or payload.get("success") is True or str(
        payload.get("status", "")
    ).lower() in {"success", "fixed", "proposal_ready", "ready"}
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
        "test_results": payload.get("test_results")
        or payload.get("test_output")
        or payload.get("tests")
        or "AI fixer reported success; host must re-run tests before application",
        "base_sha": str(head).lower(),
        "target_branch": "main",
        "verification_command": command,
        "source": str(payload.get("source") or "self_healing_agent.ai_fixer"),
    }


__all__ = ["route_successful_ai_fix"]
