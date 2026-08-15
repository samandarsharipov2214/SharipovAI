"""Bounded operational cleanup contract for Architecture V2.

This module turns Storage Budget V2 decisions into an executable, adapter-driven
cleanup plan without shell access, Docker socket access, path deletion, privilege
changes, or authority over protected storage classes. Concrete host-side cleanup
adapters can be wired later behind the narrow ``CleanupAdapter`` protocol.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from autonomous_trading.storage_budget_v2 import (
    StorageBudget,
    StorageClass,
    StorageSnapshot,
    pressure_level,
    retention_decision,
)


class CleanupOperation(StrEnum):
    PRUNE_BUILD_CACHE = "prune_build_cache"
    DELETE_EXPIRED_TEMPORARY = "delete_expired_temporary"
    ROTATE_EXPIRED_LOGS = "rotate_expired_logs"


_OPERATION_BY_CLASS = {
    StorageClass.BUILD_CACHE: CleanupOperation.PRUNE_BUILD_CACHE,
    StorageClass.TEMPORARY: CleanupOperation.DELETE_EXPIRED_TEMPORARY,
    StorageClass.APPLICATION_LOG: CleanupOperation.ROTATE_EXPIRED_LOGS,
}


@dataclass(frozen=True, slots=True)
class CleanupTarget:
    target_id: str
    storage_class: StorageClass
    estimated_reclaim_bytes: int
    age_days: int | None = None

    def __post_init__(self) -> None:
        if not self.target_id.strip():
            raise ValueError("target_id must be non-empty")
        if self.estimated_reclaim_bytes <= 0:
            raise ValueError("estimated_reclaim_bytes must be positive")
        if self.age_days is not None and self.age_days < 0:
            raise ValueError("age_days cannot be negative")


@dataclass(frozen=True, slots=True)
class CleanupAction:
    target: CleanupTarget
    operation: CleanupOperation
    reclaim_limit_bytes: int

    def __post_init__(self) -> None:
        if self.reclaim_limit_bytes <= 0:
            raise ValueError("reclaim_limit_bytes must be positive")
        if self.reclaim_limit_bytes > self.target.estimated_reclaim_bytes:
            raise ValueError("reclaim_limit_bytes cannot exceed target estimate")


@dataclass(frozen=True, slots=True)
class CleanupPlan:
    pressure: str
    actions: tuple[CleanupAction, ...]
    max_reclaim_bytes: int

    @property
    def planned_reclaim_bytes(self) -> int:
        return sum(action.reclaim_limit_bytes for action in self.actions)


@dataclass(frozen=True, slots=True)
class CleanupResult:
    target_id: str
    storage_class: StorageClass
    operation: CleanupOperation
    requested_limit_bytes: int
    reclaimed_bytes: int


class CleanupAdapter(Protocol):
    """Narrow host-side adapter contract; implementation must honor the byte cap."""

    def reclaim(self, action: CleanupAction) -> int:
        """Return the number of bytes actually reclaimed for exactly this action."""


def _eligible(target: CleanupTarget, budget: StorageBudget) -> bool:
    decision = retention_decision(target.storage_class, age_days=target.age_days)
    if not decision.automatic_cleanup_allowed:
        return False
    if target.storage_class is StorageClass.APPLICATION_LOG:
        return target.age_days is not None and target.age_days >= budget.log_retention_days
    return target.storage_class in (StorageClass.TEMPORARY, StorageClass.BUILD_CACHE)


def build_cleanup_plan(
    snapshot: StorageSnapshot,
    budget: StorageBudget,
    inventory: tuple[CleanupTarget, ...],
    *,
    max_reclaim_bytes: int,
    max_actions: int = 8,
) -> CleanupPlan:
    """Build a deterministic, byte-capped plan using only disposable/expired data."""
    if max_reclaim_bytes <= 0:
        raise ValueError("max_reclaim_bytes must be positive")
    if max_actions <= 0:
        raise ValueError("max_actions must be positive")

    pressure = pressure_level(snapshot, budget)
    if pressure == "normal":
        return CleanupPlan(pressure=pressure, actions=(), max_reclaim_bytes=max_reclaim_bytes)

    remaining = max_reclaim_bytes
    actions: list[CleanupAction] = []
    seen_ids: set[str] = set()

    for target in inventory:
        if len(actions) >= max_actions or remaining <= 0:
            break
        if target.target_id in seen_ids:
            raise ValueError(f"duplicate cleanup target_id: {target.target_id}")
        seen_ids.add(target.target_id)
        if not _eligible(target, budget):
            continue

        operation = _OPERATION_BY_CLASS.get(target.storage_class)
        if operation is None:
            continue
        reclaim_limit = min(target.estimated_reclaim_bytes, remaining)
        actions.append(
            CleanupAction(
                target=target,
                operation=operation,
                reclaim_limit_bytes=reclaim_limit,
            )
        )
        remaining -= reclaim_limit

    return CleanupPlan(
        pressure=pressure,
        actions=tuple(actions),
        max_reclaim_bytes=max_reclaim_bytes,
    )


def execute_cleanup(plan: CleanupPlan, adapter: CleanupAdapter) -> tuple[CleanupResult, ...]:
    """Execute only a previously bounded plan and fail closed on adapter violations."""
    if plan.planned_reclaim_bytes > plan.max_reclaim_bytes:
        raise ValueError("cleanup plan exceeds max_reclaim_bytes")

    results: list[CleanupResult] = []
    total_reclaimed = 0
    for action in plan.actions:
        if action.target.storage_class not in _OPERATION_BY_CLASS:
            raise ValueError("cleanup action contains a protected or unsupported storage class")
        expected_operation = _OPERATION_BY_CLASS[action.target.storage_class]
        if action.operation is not expected_operation:
            raise ValueError("cleanup action operation does not match storage class")

        reclaimed = adapter.reclaim(action)
        if isinstance(reclaimed, bool) or not isinstance(reclaimed, int):
            raise TypeError("cleanup adapter must return reclaimed bytes as int")
        if reclaimed < 0:
            raise ValueError("cleanup adapter returned negative reclaimed bytes")
        if reclaimed > action.reclaim_limit_bytes:
            raise ValueError("cleanup adapter exceeded action reclaim limit")
        total_reclaimed += reclaimed
        if total_reclaimed > plan.max_reclaim_bytes:
            raise ValueError("cleanup adapter exceeded plan reclaim limit")
        results.append(
            CleanupResult(
                target_id=action.target.target_id,
                storage_class=action.target.storage_class,
                operation=action.operation,
                requested_limit_bytes=action.reclaim_limit_bytes,
                reclaimed_bytes=reclaimed,
            )
        )
    return tuple(results)


def verify_cleanup(
    before: StorageSnapshot,
    after: StorageSnapshot,
    results: tuple[CleanupResult, ...],
) -> bool:
    """Verify that a reported cleanup produced non-regressive filesystem pressure."""
    if before.total_bytes != after.total_bytes:
        return False
    reported_reclaimed = sum(result.reclaimed_bytes for result in results)
    if reported_reclaimed == 0:
        return after.free_bytes >= before.free_bytes and after.used_bytes <= before.used_bytes
    return after.free_bytes > before.free_bytes and after.used_bytes < before.used_bytes


__all__ = [
    "CleanupAction",
    "CleanupAdapter",
    "CleanupOperation",
    "CleanupPlan",
    "CleanupResult",
    "CleanupTarget",
    "build_cleanup_plan",
    "execute_cleanup",
    "verify_cleanup",
]
