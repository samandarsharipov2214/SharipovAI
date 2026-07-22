"""Persistent fail-closed execution kill switch.

The environment flag is the outer hard lock. This repository adds a durable
latch that survives process restarts and is tripped automatically after any
ambiguous exchange outcome or reconciliation failure.
"""
from __future__ import annotations

import os
import time
from dataclasses import asdict, dataclass
from typing import Any

from storage import ProjectDatabase, VersionConflict

_NAMESPACE = "execution_kill_switch_v2"
_KEY = "testnet"
_TRUE = {"1", "true", "yes", "on"}
_CLEAR_CONFIRMATION = "I_ACKNOWLEDGE_RECONCILIATION_IS_CLEAN"


@dataclass(frozen=True, slots=True)
class KillSwitchState:
    active: bool
    generation: int
    reason: str
    actor: str
    updated_at_ms: int
    source: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class PersistentExecutionKillSwitch:
    """Durable latch with optimistic concurrency and explicit reset rules."""

    def __init__(self, database: ProjectDatabase | None = None) -> None:
        self.database = database or ProjectDatabase()
        self.database.initialize()

    def state(self) -> KillSwitchState:
        env_active = os.getenv("EXECUTION_KILL_SWITCH", "1").strip().lower() in _TRUE
        current = self.database.get_json(_NAMESPACE, _KEY)
        if current is None:
            return KillSwitchState(
                active=env_active,
                generation=0,
                reason="environment_kill_switch" if env_active else "not_latched",
                actor="environment",
                updated_at_ms=0,
                source="environment",
            )
        payload = dict(current["value"])
        persisted = KillSwitchState(
            active=bool(payload.get("active", True)),
            generation=int(payload.get("generation", current["version"])),
            reason=str(payload.get("reason", "unknown")),
            actor=str(payload.get("actor", "unknown")),
            updated_at_ms=int(payload.get("updated_at_ms", 0)),
            source=str(payload.get("source", "persistent")),
        )
        if env_active and not persisted.active:
            return KillSwitchState(
                active=True,
                generation=persisted.generation,
                reason="environment_kill_switch",
                actor="environment",
                updated_at_ms=persisted.updated_at_ms,
                source="environment+persistent",
            )
        return persisted

    def assert_open(self) -> KillSwitchState:
        state = self.state()
        if state.active:
            raise RuntimeError(f"Execution kill switch is active: {state.reason}")
        return state

    def trip(self, *, reason: str, actor: str, source: str = "runtime") -> KillSwitchState:
        clean_reason = _required(reason, "reason")
        clean_actor = _required(actor, "actor")
        now_ms = int(time.time() * 1000)
        for _ in range(3):
            current = self.database.get_json(_NAMESPACE, _KEY)
            version = int(current["version"]) if current else 0
            generation = int(current["value"].get("generation", 0)) + 1 if current else 1
            state = KillSwitchState(
                active=True,
                generation=generation,
                reason=clean_reason,
                actor=clean_actor,
                updated_at_ms=now_ms,
                source=_required(source, "source"),
            )
            try:
                self.database.put_json(
                    _NAMESPACE,
                    _KEY,
                    state.to_dict(),
                    expected_version=version,
                )
                return state
            except VersionConflict:
                continue
        raise RuntimeError("cannot persist execution kill switch after concurrent updates")

    def clear(
        self,
        *,
        actor: str,
        reconciliation_restart_safe: bool,
        unresolved_execution_count: int,
        confirmation: str,
    ) -> KillSwitchState:
        if confirmation != _CLEAR_CONFIRMATION:
            raise RuntimeError("invalid kill switch clear confirmation")
        if not reconciliation_restart_safe:
            raise RuntimeError("kill switch cannot clear before restart-safe reconciliation")
        if int(unresolved_execution_count) != 0:
            raise RuntimeError("kill switch cannot clear with unresolved executions")
        if os.getenv("EXECUTION_KILL_SWITCH", "1").strip().lower() in _TRUE:
            raise RuntimeError("environment kill switch remains active")

        current = self.database.get_json(_NAMESPACE, _KEY)
        version = int(current["version"]) if current else 0
        generation = int(current["value"].get("generation", 0)) + 1 if current else 1
        state = KillSwitchState(
            active=False,
            generation=generation,
            reason="manually_cleared_after_reconciliation",
            actor=_required(actor, "actor"),
            updated_at_ms=int(time.time() * 1000),
            source="manual_reconciliation_gate",
        )
        self.database.put_json(
            _NAMESPACE,
            _KEY,
            state.to_dict(),
            expected_version=version,
        )
        return state


def _required(value: str, name: str) -> str:
    clean = str(value).strip()
    if not clean:
        raise ValueError(f"{name} is required")
    return clean[:512]


__all__ = [
    "KillSwitchState",
    "PersistentExecutionKillSwitch",
]
