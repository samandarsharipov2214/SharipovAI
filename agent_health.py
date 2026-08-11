"""Read-only evidence-based health projection for SharipovAI.

This compatibility module never starts workers, refreshes news, or reads the
retired PaperActivityEngine. Health comes only from the canonical
``ai_organ_runtime`` evidence written into ProjectDatabase by the runtime
monitor. Missing/stale evidence is reported as unknown/degraded, never healthy.
"""
from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass
from typing import Any, Callable

from ai_architecture_registry import CANONICAL_AI_ORGANS
from storage import ProjectDatabase


@dataclass(frozen=True, init=False)
class AgentDefinition:
    id: str
    name: str
    responsibility: str
    check: Callable[[], dict[str, Any]]

    def __init__(
        self,
        id_or_name: str,
        name_or_responsibility: str,
        responsibility_or_check: str | Callable[[], dict[str, Any]],
        check: Callable[[], dict[str, Any]] | None = None,
    ) -> None:
        if check is None:
            name = id_or_name
            responsibility = name_or_responsibility
            resolved_check = responsibility_or_check
            if not callable(resolved_check):
                raise TypeError("check must be callable")
            agent_id = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_") or "agent"
        else:
            agent_id = id_or_name
            name = name_or_responsibility
            responsibility = str(responsibility_or_check)
            resolved_check = check
        object.__setattr__(self, "id", agent_id)
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "responsibility", responsibility)
        object.__setattr__(self, "check", resolved_check)


def _safe_check(check: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    checked_at = int(time.time())
    try:
        result = check() or {}
        ok = bool(result.get("ok"))
        return {
            "ok": ok,
            "checked_at": int(result.get("checked_at") or checked_at),
            "evidence": list(result.get("evidence", [])),
            "last_action": result.get("last_action"),
            "last_error": None if ok else result.get("last_error", "проверка не подтверждена"),
            "details": dict(result.get("details", {})),
            "stale": bool(result.get("stale", False)),
            "runtime_status": result.get("runtime_status"),
        }
    except Exception as exc:
        return {
            "ok": False,
            "checked_at": checked_at,
            "evidence": [],
            "last_action": None,
            "last_error": f"{type(exc).__name__}: {exc}",
            "details": {},
            "stale": False,
            "runtime_status": "unknown",
        }


def _runtime_check(organ_id: str) -> dict[str, Any]:
    database = ProjectDatabase()
    database.initialize()
    current = database.get_json("ai_organ_runtime", organ_id)
    if current is None or not isinstance(current.get("value"), dict):
        return {
            "ok": False,
            "evidence": [],
            "last_error": "canonical runtime evidence отсутствует",
            "runtime_status": "unknown",
            "details": {"organ_id": organ_id, "source": "ProjectDatabase.ai_organ_runtime"},
        }

    value = dict(current["value"])
    checked_at_ms = int(value.get("checked_at_ms") or current.get("updated_at_ms") or 0)
    now_ms = int(time.time() * 1000)
    maximum_age_seconds = _evidence_max_age_seconds()
    age_seconds = max(0.0, (now_ms - checked_at_ms) / 1000.0) if checked_at_ms > 0 else None
    stale = age_seconds is None or age_seconds > maximum_age_seconds
    runtime_status = str(value.get("status") or "unknown").lower()
    evidence = [str(item) for item in value.get("evidence", []) if str(item).strip()]
    blockers = [str(item) for item in value.get("blockers", []) if str(item).strip()]
    ok = runtime_status == "healthy" and not stale and not blockers
    errors = list(blockers)
    if stale:
        errors.append(
            "canonical runtime evidence stale"
            if age_seconds is not None
            else "canonical runtime evidence has no timestamp"
        )
    return {
        "ok": ok,
        "evidence": evidence,
        "last_action": evidence[-1] if evidence else None,
        "last_error": "; ".join(errors) or (None if ok else f"runtime status={runtime_status}"),
        "runtime_status": runtime_status,
        "checked_at": checked_at_ms // 1000 if checked_at_ms > 0 else int(time.time()),
        "stale": stale,
        "details": {
            "organ_id": organ_id,
            "source": "ProjectDatabase.ai_organ_runtime",
            "age_seconds": age_seconds,
            "blockers": blockers,
        },
    }


def _definitions() -> list[AgentDefinition]:
    return [
        AgentDefinition(
            organ.id,
            organ.name,
            organ.responsibility,
            lambda organ_id=organ.id: _runtime_check(organ_id),
        )
        for organ in CANONICAL_AI_ORGANS
    ]


def build_agent_health_snapshot() -> dict[str, Any]:
    generated_at = int(time.time())
    agents: list[dict[str, Any]] = []
    for definition in _definitions():
        check = _safe_check(definition.check)
        evidence_count = len(check.get("evidence", []))
        runtime_status = str(check.get("runtime_status") or "unknown")
        if check["ok"]:
            status, score = "working", 100
        elif evidence_count or runtime_status in {"degraded", "blocked"} or check.get("stale"):
            status = "degraded"
            score = 0 if runtime_status == "blocked" else 50
        else:
            status, score = "unknown", None
        agents.append(
            {
                "id": definition.id,
                "name": definition.name,
                "responsibility": definition.responsibility,
                "status": status,
                "runtime_status": runtime_status,
                "quality_score": score,
                "health_score": score,
                "checked_at": check["checked_at"],
                "changed_at": check["checked_at"],
                "last_seen": check["checked_at"] if evidence_count else None,
                "last_action": check.get("last_action"),
                "last_error": check.get("last_error"),
                "evidence": check.get("evidence", []),
                "evidence_count": evidence_count,
                "stale": bool(check.get("stale")),
                "details": check.get("details", {}),
            }
        )
    working = sum(agent["status"] == "working" for agent in agents)
    degraded = sum(agent["status"] == "degraded" for agent in agents)
    unknown = sum(agent["status"] == "unknown" for agent in agents)
    return {
        "status": "ok" if degraded == 0 and unknown == 0 else "warning",
        "generated_at": generated_at,
        "summary": {
            "total_bots": len(agents),
            "canonical_ai_count": len(agents),
            "active": working,
            "warnings": degraded + unknown,
            "working": working,
            "degraded": degraded,
            "unknown": unknown,
        },
        "agents": agents,
        "bots": agents,
        "truth_policy": (
            "No decorative score: health is read-only ProjectDatabase ai_organ_runtime evidence; "
            "missing or stale evidence is never healthy."
        ),
    }


def _evidence_max_age_seconds() -> float:
    try:
        value = float(os.getenv("AI_ORGAN_EVIDENCE_MAX_AGE_SECONDS", "300"))
    except ValueError:
        value = 300.0
    return min(max(value, 30.0), 3600.0)


__all__ = ["AgentDefinition", "build_agent_health_snapshot"]
