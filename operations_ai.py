"""Operational AI services for keeping SharipovAI healthy.

These agents do not trade and do not invent intelligence. They inspect canonical
runtime evidence, classify incidents, and propose or execute only explicitly
allow-listed recovery actions.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Callable

from agent_health import build_agent_health_snapshot
from paper_activity_autorun import paper_activity_autorun_status, start_paper_activity_autorun


@dataclass(frozen=True)
class RecoveryAction:
    action_id: str
    title: str
    safe: bool
    execute: Callable[[], dict[str, Any]]


def _restart_virtual_account_autorun() -> dict[str, Any]:
    """Idempotently ensure the virtual-account autorun thread is alive."""

    before = paper_activity_autorun_status()
    result = start_paper_activity_autorun()
    after = paper_activity_autorun_status()
    return {"status": "ok", "before": before, "result": result, "after": after}


SAFE_RECOVERY_ACTIONS: dict[str, RecoveryAction] = {
    "restart_virtual_account_autorun": RecoveryAction(
        action_id="restart_virtual_account_autorun",
        title="Перезапустить безопасный autorun виртуального счёта",
        safe=True,
        execute=_restart_virtual_account_autorun,
    ),
}


def diagnose_system() -> dict[str, Any]:
    """Return an evidence-based incident report for the whole agent network."""

    snapshot = build_agent_health_snapshot()
    incidents: list[dict[str, Any]] = []
    for agent in snapshot.get("agents", []):
        status = str(agent.get("status", "unknown"))
        if status == "working":
            continue
        severity = "high" if agent.get("name") in {"General Controller", "Risk Engine", "Security Guard"} else "medium"
        incidents.append(
            {
                "agent": agent.get("name"),
                "severity": severity,
                "status": status,
                "problem": agent.get("last_error") or "нет подтверждения корректной работы",
                "checked_at": agent.get("checked_at"),
                "evidence": agent.get("evidence", []),
                "recommended_action": _recommended_action(agent),
            }
        )

    return {
        "status": "healthy" if not incidents else "degraded",
        "generated_at": int(time.time()),
        "summary": {
            "incident_count": len(incidents),
            "high": len([item for item in incidents if item["severity"] == "high"]),
            "medium": len([item for item in incidents if item["severity"] == "medium"]),
            "working_agents": snapshot.get("summary", {}).get("working", 0),
            "total_agents": snapshot.get("summary", {}).get("total_bots", 0),
        },
        "incidents": incidents,
        "agent_health": snapshot,
        "real_orders_blocked": True,
    }


def _recommended_action(agent: dict[str, Any]) -> dict[str, Any]:
    name = str(agent.get("name", ""))
    error = str(agent.get("last_error", ""))
    if "autorun" in error.lower() or name == "Paper Trading Bot":
        return {
            "action_id": "restart_virtual_account_autorun",
            "title": SAFE_RECOVERY_ACTIONS["restart_virtual_account_autorun"].title,
            "automatic_allowed": True,
        }
    return {
        "action_id": None,
        "title": "Требуется диагностика и исправление причины; автоматическое действие не разрешено",
        "automatic_allowed": False,
    }


def heal_system(*, execute_safe_actions: bool = False) -> dict[str, Any]:
    """Diagnose and optionally execute allow-listed, reversible recovery actions."""

    diagnosis_before = diagnose_system()
    executed: list[dict[str, Any]] = []
    seen: set[str] = set()

    if execute_safe_actions:
        for incident in diagnosis_before.get("incidents", []):
            recommendation = incident.get("recommended_action", {})
            action_id = recommendation.get("action_id")
            if not action_id or action_id in seen:
                continue
            action = SAFE_RECOVERY_ACTIONS.get(str(action_id))
            if not action or not action.safe:
                continue
            seen.add(action.action_id)
            try:
                result = action.execute()
                executed.append({"action_id": action.action_id, "status": "executed", "result": result})
            except Exception as exc:
                executed.append({"action_id": action.action_id, "status": "failed", "error": f"{type(exc).__name__}: {exc}"})

    diagnosis_after = diagnose_system()
    return {
        "status": "ok" if diagnosis_after.get("status") == "healthy" else "degraded",
        "generated_at": int(time.time()),
        "execute_safe_actions": execute_safe_actions,
        "executed": executed,
        "before": diagnosis_before,
        "after": diagnosis_after,
        "real_orders_blocked": True,
    }


def cto_report() -> dict[str, Any]:
    """Return a compact management report derived from AI Doctor evidence."""

    diagnosis = diagnose_system()
    incidents = diagnosis.get("incidents", [])
    priorities = sorted(incidents, key=lambda item: 0 if item.get("severity") == "high" else 1)
    return {
        "status": diagnosis.get("status"),
        "generated_at": diagnosis.get("generated_at"),
        "mission": "Стабильность, правдивость, безопасность и измеримая эффективность SharipovAI.",
        "summary": diagnosis.get("summary", {}),
        "top_priorities": priorities[:5],
        "release_gate": {
            "ready": not incidents,
            "reason": "нет открытых инцидентов" if not incidents else "есть неподтверждённые или деградированные модули",
            "real_orders_allowed": False,
        },
    }
