"""Fail-closed storage budget contract for Architecture V2.

This module classifies storage classes and decides whether automated retention is
allowed. It never deletes data itself. Production state, evidence, rollback
artifacts and backups are always protected from automatic deletion.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class StorageClass(StrEnum):
    PRODUCTION_STATE = "production_state"
    EVIDENCE = "evidence"
    ROLLBACK = "rollback"
    BACKUP = "backup"
    APPLICATION_LOG = "application_log"
    TEMPORARY = "temporary"
    BUILD_CACHE = "build_cache"


_PROTECTED = frozenset({
    StorageClass.PRODUCTION_STATE,
    StorageClass.EVIDENCE,
    StorageClass.ROLLBACK,
    StorageClass.BACKUP,
})
_DISPOSABLE = frozenset({StorageClass.TEMPORARY, StorageClass.BUILD_CACHE})


@dataclass(frozen=True, slots=True)
class StorageBudget:
    soft_limit_bytes: int
    hard_limit_bytes: int
    min_free_bytes: int
    log_retention_days: int = 14

    def __post_init__(self) -> None:
        if self.soft_limit_bytes <= 0 or self.hard_limit_bytes <= 0 or self.min_free_bytes <= 0:
            raise ValueError("storage limits must be positive")
        if self.soft_limit_bytes >= self.hard_limit_bytes:
            raise ValueError("soft_limit_bytes must be less than hard_limit_bytes")
        if self.log_retention_days <= 0:
            raise ValueError("log_retention_days must be positive")


@dataclass(frozen=True, slots=True)
class StorageSnapshot:
    total_bytes: int
    used_bytes: int
    free_bytes: int

    def __post_init__(self) -> None:
        if self.total_bytes <= 0 or self.used_bytes < 0 or self.free_bytes < 0:
            raise ValueError("snapshot byte counts are invalid")
        if self.used_bytes + self.free_bytes > self.total_bytes:
            raise ValueError("used_bytes + free_bytes cannot exceed total_bytes")


@dataclass(frozen=True, slots=True)
class RetentionDecision:
    storage_class: StorageClass
    automatic_cleanup_allowed: bool
    reason: str


def pressure_level(snapshot: StorageSnapshot, budget: StorageBudget) -> str:
    if snapshot.free_bytes < budget.min_free_bytes or snapshot.used_bytes >= budget.hard_limit_bytes:
        return "hard"
    if snapshot.used_bytes >= budget.soft_limit_bytes:
        return "soft"
    return "normal"


def retention_decision(storage_class: StorageClass, *, age_days: int | None = None) -> RetentionDecision:
    if storage_class in _PROTECTED:
        return RetentionDecision(storage_class, False, "protected data is never automatically deleted")
    if storage_class in _DISPOSABLE:
        return RetentionDecision(storage_class, True, "disposable storage may be reclaimed")
    if storage_class is StorageClass.APPLICATION_LOG:
        if age_days is None or age_days < 0:
            return RetentionDecision(storage_class, False, "log age must be known before cleanup")
        return RetentionDecision(storage_class, True, "log cleanup requires caller retention policy")
    return RetentionDecision(storage_class, False, "unknown storage class fails closed")


def cleanup_candidates(
    snapshot: StorageSnapshot,
    budget: StorageBudget,
    inventory: tuple[tuple[StorageClass, int | None], ...],
) -> tuple[RetentionDecision, ...]:
    """Return eligible cleanup classes without performing destructive actions."""
    if pressure_level(snapshot, budget) == "normal":
        return ()
    decisions: list[RetentionDecision] = []
    for storage_class, age_days in inventory:
        decision = retention_decision(storage_class, age_days=age_days)
        if storage_class is StorageClass.APPLICATION_LOG and decision.automatic_cleanup_allowed:
            if age_days is None or age_days < budget.log_retention_days:
                continue
        if decision.automatic_cleanup_allowed:
            decisions.append(decision)
    return tuple(decisions)


__all__ = [
    "RetentionDecision",
    "StorageBudget",
    "StorageClass",
    "StorageSnapshot",
    "cleanup_candidates",
    "pressure_level",
    "retention_decision",
]
