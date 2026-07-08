"""Dashboard integration helper for SharipovAI Policy Action Guard."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from fastapi import Request

from learning.policy_action_guard import guard_action
from learning.policy_journal import PolicyJournal


def check_dashboard_action(
    *,
    action_type: str,
    actor: str,
    topic: str = "general",
    request: Request | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Check whether a dashboard/bot action can run under latest policy advice."""

    latest = latest_policy_advice()
    action = {"action_type": action_type, "actor": actor, "topic": topic, **(extra or {})}
    decision = guard_action(action, latest)
    if decision.get("decision") in {"block", "manual_review", "reject"}:
        _record_blocked_action(decision, request=request)
    return decision


def latest_policy_advice() -> dict[str, Any] | None:
    """Read latest policy advice from the runtime journal."""

    return PolicyJournal(_journal_path()).snapshot().get("latest_advice")


def guarded_response(decision: dict[str, Any]) -> dict[str, Any]:
    """Return a compact blocked response for API endpoints."""

    return {
        "status": "blocked",
        "error": "policy_guard_blocked",
        "decision": decision.get("decision"),
        "reason": decision.get("reason"),
        "action_type": decision.get("action_type"),
        "recommended_action": decision.get("recommended_action"),
        "must_notify_owner": decision.get("must_notify_owner", False),
        "instructions": decision.get("instructions", []),
    }


def _journal_path() -> Path:
    return Path(os.getenv("POLICY_JOURNAL_FILE", "data/policy_journal.json"))


def _record_blocked_action(decision: dict[str, Any], *, request: Request | None = None) -> None:
    """Best-effort audit event for policy blocked dashboard actions."""

    try:
        from dashboard.app import _record_security_event
    except Exception:
        return
    try:
        _record_security_event(
            "policy_guard_blocked_action",
            _session_username(request) or "anonymous",
            request,
            {
                "decision": decision.get("decision"),
                "reason": decision.get("reason"),
                "action_type": decision.get("action_type"),
                "actor": decision.get("actor"),
                "topic": decision.get("topic"),
            },
        )
    except Exception:
        return


def _session_username(request: Request | None) -> str | None:
    if request is None:
        return None
    try:
        from dashboard.app import _session_username as app_session_username

        return app_session_username(request)
    except Exception:
        return None
