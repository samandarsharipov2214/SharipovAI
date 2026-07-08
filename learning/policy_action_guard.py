"""Policy Action Guard for SharipovAI.

This module converts the latest policy/legal controller advice into a practical
allow/caution/manual_review/block decision before risky bot actions run.
"""

from __future__ import annotations

from typing import Any


HIGH_RISK_ACTIONS = {"trade", "crypto_trade", "stock_trade", "withdrawal", "user_access", "data_export"}
MEDIUM_RISK_ACTIONS = {"paper_trade", "bot_learning", "portfolio_rebalance", "news_publish"}
SAFE_ACTIONS = {"read_dashboard", "health_check", "paper_report", "learning_summary"}


def guard_action(action: dict[str, Any], latest_advice: dict[str, Any] | None) -> dict[str, Any]:
    """Decide whether a requested bot action is allowed."""

    action_type = str(action.get("action_type", "")).strip().lower()
    actor = str(action.get("actor", "unknown"))
    topic = str(action.get("topic", "unknown"))
    advice = latest_advice or {}
    recommended = str(advice.get("recommended_action", "continue")).strip().lower() or "continue"

    if not action_type:
        return _decision("reject", action_type, actor, topic, "missing_action_type", advice)

    if action_type in SAFE_ACTIONS:
        return _decision("allow", action_type, actor, topic, "safe_action", advice)

    if recommended == "block_action" and action_type in HIGH_RISK_ACTIONS:
        return _decision("block", action_type, actor, topic, "policy_block_action", advice)

    if recommended == "manual_review" and action_type in HIGH_RISK_ACTIONS:
        return _decision("manual_review", action_type, actor, topic, "manual_review_required", advice)

    if recommended == "caution" and action_type in HIGH_RISK_ACTIONS | MEDIUM_RISK_ACTIONS:
        return _decision("caution", action_type, actor, topic, "policy_caution", advice)

    if recommended == "watch" and action_type in HIGH_RISK_ACTIONS:
        return _decision("caution", action_type, actor, topic, "policy_watch", advice)

    return _decision("allow", action_type, actor, topic, "no_policy_block", advice)


def guard_batch(actions: list[dict[str, Any]], latest_advice: dict[str, Any] | None) -> dict[str, Any]:
    """Evaluate multiple actions and summarize the strictest decision."""

    decisions = [guard_action(action, latest_advice) for action in actions]
    strictest = _strictest(decisions)
    return {"status": "ok", "decision": strictest, "decisions": decisions, "allowed": strictest in {"allow", "caution"}}


def _decision(result: str, action_type: str, actor: str, topic: str, reason: str, advice: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": "ok",
        "decision": result,
        "allowed": result in {"allow", "caution"},
        "action_type": action_type,
        "actor": actor,
        "topic": topic,
        "reason": reason,
        "recommended_action": advice.get("recommended_action", "continue"),
        "must_notify_owner": bool(advice.get("must_notify_owner", False)) or result in {"block", "manual_review"},
        "instructions": _instructions(result),
    }


def _strictest(decisions: list[dict[str, Any]]) -> str:
    order = {"allow": 1, "caution": 2, "manual_review": 3, "block": 4, "reject": 5}
    if not decisions:
        return "allow"
    return max((decision["decision"] for decision in decisions), key=lambda item: order.get(item, 0))


def _instructions(result: str) -> list[str]:
    if result == "block":
        return ["Stop the action.", "Notify owner.", "Require manual legal/policy review before retry."]
    if result == "manual_review":
        return ["Pause the action.", "Request manual review.", "Do not execute with real money or sensitive access."]
    if result == "caution":
        return ["Proceed only in low-risk mode.", "Lower confidence.", "Log the decision and require extra source confirmation."]
    if result == "reject":
        return ["Reject malformed action request."]
    return ["Action allowed under current policy state."]
