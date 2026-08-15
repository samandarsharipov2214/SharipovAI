import pytest

from autonomous_trading.storage_budget_v2 import (
    StorageBudget,
    StorageClass,
    StorageSnapshot,
    cleanup_candidates,
    pressure_level,
    retention_decision,
)


def _budget() -> StorageBudget:
    return StorageBudget(
        soft_limit_bytes=40,
        hard_limit_bytes=50,
        min_free_bytes=10,
        log_retention_days=14,
    )


def test_budget_requires_ordered_positive_limits() -> None:
    with pytest.raises(ValueError, match="soft_limit_bytes"):
        StorageBudget(soft_limit_bytes=50, hard_limit_bytes=50, min_free_bytes=10)
    with pytest.raises(ValueError, match="positive"):
        StorageBudget(soft_limit_bytes=40, hard_limit_bytes=50, min_free_bytes=0)


def test_pressure_is_fail_closed_at_hard_limit_or_low_free_space() -> None:
    budget = _budget()
    assert pressure_level(StorageSnapshot(total_bytes=60, used_bytes=30, free_bytes=20), budget) == "normal"
    assert pressure_level(StorageSnapshot(total_bytes=60, used_bytes=40, free_bytes=20), budget) == "soft"
    assert pressure_level(StorageSnapshot(total_bytes=60, used_bytes=50, free_bytes=10), budget) == "hard"
    assert pressure_level(StorageSnapshot(total_bytes=60, used_bytes=45, free_bytes=5), budget) == "hard"


def test_protected_classes_are_never_automatic_cleanup_targets() -> None:
    for storage_class in (
        StorageClass.PRODUCTION_STATE,
        StorageClass.EVIDENCE,
        StorageClass.ROLLBACK,
        StorageClass.BACKUP,
    ):
        decision = retention_decision(storage_class)
        assert decision.automatic_cleanup_allowed is False
        assert "never automatically deleted" in decision.reason


def test_only_disposable_and_expired_logs_are_cleanup_candidates() -> None:
    budget = _budget()
    snapshot = StorageSnapshot(total_bytes=60, used_bytes=50, free_bytes=10)
    candidates = cleanup_candidates(
        snapshot,
        budget,
        (
            (StorageClass.PRODUCTION_STATE, None),
            (StorageClass.EVIDENCE, None),
            (StorageClass.ROLLBACK, None),
            (StorageClass.BACKUP, None),
            (StorageClass.APPLICATION_LOG, 7),
            (StorageClass.APPLICATION_LOG, 14),
            (StorageClass.TEMPORARY, None),
            (StorageClass.BUILD_CACHE, None),
        ),
    )
    assert tuple(item.storage_class for item in candidates) == (
        StorageClass.APPLICATION_LOG,
        StorageClass.TEMPORARY,
        StorageClass.BUILD_CACHE,
    )


def test_normal_pressure_proposes_no_cleanup() -> None:
    assert cleanup_candidates(
        StorageSnapshot(total_bytes=60, used_bytes=30, free_bytes=20),
        _budget(),
        ((StorageClass.BUILD_CACHE, None),),
    ) == ()
