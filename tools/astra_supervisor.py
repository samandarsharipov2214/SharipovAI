"""Bounded, durable local scheduler for SharipovAI Astra work.

The supervisor performs cheap local checks by default.  A separately
provisioned automation identity can run only an explicitly queued and bounded
Codex task; it never reuses a transient interactive login.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


SCHEMA = 1
LOCAL_PAPER_DIAGNOSIS = "paper_execution_diagnosis"
CODEX_TASK = "codex_engineering"
TASK_ID_RE = re.compile(r"codex-[a-z0-9-]{1,80}$")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def default_state() -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "created_at": _utc_now(),
        "updated_at": _utc_now(),
        "tasks": [{
            "id": LOCAL_PAPER_DIAGNOSIS,
            "kind": "local",
            "status": "PENDING",
            "attempts": 0,
            "max_attempts": 2,
            "requires_codex": False,
            "checkpoint": None,
        }],
        "history": [],
        "last_result": None,
        "blocker": None,
        "codex_calls": 0,
    }


def read_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return default_state()
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("schema") != SCHEMA:
        raise ValueError("unsupported Astra supervisor state")
    if not isinstance(value.get("tasks"), list) or not isinstance(value.get("history"), list):
        raise ValueError("invalid Astra supervisor state")
    return value


def write_state(path: Path, state: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    payload = dict(state)
    payload["updated_at"] = _utc_now()
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)


def resource_state() -> dict[str, Any]:
    """Use only cheap host signals; no Docker mutation or database read."""
    load = os.getloadavg()[0]
    memory = Path("/proc/meminfo").read_text(encoding="utf-8")
    values = {}
    for line in memory.splitlines():
        key, raw = line.split(":", 1)
        values[key] = int(raw.strip().split()[0]) * 1024
    available = values.get("MemAvailable", 0)
    stat = os.statvfs("/")
    disk_free = stat.f_frsize * stat.f_bavail
    return {
        "load_1m": load,
        "memory_available_bytes": available,
        "disk_free_bytes": disk_free,
        "safe": load <= 1.5 and available >= 700 * 1024**2 and disk_free >= 8 * 1024**3,
    }


def _record(state: dict[str, Any], event: str, **detail: Any) -> None:
    state["history"].append({"at": _utc_now(), "event": event, **detail})
    del state["history"][:-100]


def next_action(
    state: dict[str, Any], resources: Mapping[str, Any], *, codex_available: bool = False,
) -> dict[str, Any]:
    pending = [task for task in state["tasks"] if task.get("status") == "PENDING"]
    if not pending:
        state["blocker"] = None
        return {"action": "IDLE", "reason": "queue_empty", "needs_codex": False}
    if not resources.get("safe"):
        state["blocker"] = {"code": "RESOURCE_GUARD", "at": _utc_now(), "detail": dict(resources)}
        return {"action": "WAIT", "reason": "resource_guard", "needs_codex": False}
    task = pending[0]
    if int(task.get("attempts", 0)) >= int(task.get("max_attempts", 0)):
        task["status"] = "FAILED"
        task["checkpoint"] = "retry_budget_exhausted"
        _record(state, "task_failed", task_id=task["id"], reason="retry_budget_exhausted")
        return next_action(state, resources)
    if task.get("requires_codex"):
        # A service must receive a provisioned, scoped credential explicitly.
        # Never reuse, copy, or probe an interactive Codex login here.
        if not codex_available:
            state["blocker"] = {"code": "CODEX_AUTOMATION_AUTH_REQUIRED", "at": _utc_now(),
                                "detail": "Provision a scoped Codex access token through the service environment."}
            return {"action": "WAIT", "reason": "codex_automation_auth_required", "needs_codex": True}
        return {"action": "RUN_CODEX", "reason": "explicit_queued_task", "task_id": task["id"],
                "needs_codex": True}
    return {"action": "RUN_LOCAL", "reason": "local_task_pending", "task_id": task["id"], "needs_codex": False}


def complete(state: dict[str, Any], task_id: str, result: Mapping[str, Any]) -> None:
    task = next((item for item in state["tasks"] if item.get("id") == task_id), None)
    if task is None or task.get("status") != "PENDING":
        raise ValueError("task is not pending")
    task["attempts"] = int(task.get("attempts", 0)) + 1
    ok = result.get("status") == "VERIFIED"
    if task.get("requires_codex"):
        state["codex_calls"] = int(state.get("codex_calls", 0)) + 1
    # Retain a durable checkpoint and wait for the next scheduled wakeup
    # while a bounded retry budget remains.  This prevents a failed service
    # invocation from becoming an invisible, unbounded retry loop.
    exhausted = int(task["attempts"]) >= int(task.get("max_attempts", 0))
    task["status"] = "VERIFIED" if ok else ("FAILED" if exhausted else "PENDING")
    task["checkpoint"] = result.get("output")
    state["last_result"] = dict(result)
    _record(state, "task_completed" if ok else "task_retry_pending" if not exhausted else "task_failed",
            task_id=task_id, result=dict(result))


def enqueue_codex_task(state: dict[str, Any], task_id: str) -> None:
    """Add one bounded task after its prompt was placed in the protected queue."""
    if not TASK_ID_RE.fullmatch(task_id):
        raise ValueError("invalid Codex task id")
    if any(item.get("id") == task_id for item in state["tasks"]):
        raise ValueError("task id already exists")
    state["tasks"].append({"id": task_id, "kind": CODEX_TASK, "status": "PENDING",
                           "attempts": 0, "max_attempts": 2, "requires_codex": True,
                           "checkpoint": None})
    _record(state, "task_queued", task_id=task_id, kind=CODEX_TASK)


def status_markdown(state: Mapping[str, Any], resources: Mapping[str, Any], action: Mapping[str, Any]) -> str:
    lines = ["# ASTRA STATUS", "", f"Updated: {state.get('updated_at', _utc_now())}", "",
             f"State: `{action['action']}` — `{action['reason']}`", "",
             "## Tasks", ""]
    for task in state["tasks"]:
        lines.append(f"- `{task['status']}` {task['id']} (attempts {task['attempts']}/{task['max_attempts']})")
    lines += ["", "## Resource guard", "", "```json", json.dumps(dict(resources), sort_keys=True), "```", "",
              "## Automation", "", f"- Codex calls made by supervisor: {state.get('codex_calls', 0)}",
              "- Codex is invoked only for an explicitly queued task and a separately provisioned scoped automation credential.",
              "- Interactive Codex logins are never copied, exported, or used as a background credential."]
    if state.get("blocker"):
        lines += ["", "## Blocker", "", "```json", json.dumps(state["blocker"], sort_keys=True), "```"]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--status", type=Path, required=True)
    parser.add_argument("--complete", metavar="TASK_ID")
    parser.add_argument("--result", type=Path)
    parser.add_argument("--codex-available", action="store_true")
    parser.add_argument("--enqueue-codex", metavar="TASK_ID")
    args = parser.parse_args(argv)
    state = read_state(args.state)
    resources = resource_state()
    if args.enqueue_codex:
        enqueue_codex_task(state, args.enqueue_codex)
    if args.complete:
        if not args.result:
            parser.error("--complete requires --result")
        complete(state, args.complete, json.loads(args.result.read_text(encoding="utf-8")))
    action = next_action(state, resources, codex_available=args.codex_available)
    write_state(args.state, state)
    args.status.parent.mkdir(parents=True, exist_ok=True)
    args.status.write_text(status_markdown(state, resources, action), encoding="utf-8")
    os.chmod(args.status, 0o600)
    print(json.dumps(action, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
