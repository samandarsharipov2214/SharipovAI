import pytest

from autonomous_trading.storage_budget_v2 import StorageBudget, StorageClass, StorageSnapshot
from autonomous_trading.storage_cleanup_v2 import (
    CleanupAction,
    CleanupOperation,
    CleanupPlan,
    CleanupTarget,
    build_cleanup_plan,
    execute_cleanup,
    verify_cleanup,
)


def _budget() -> StorageBudget:
    return StorageBudget(
        soft_limit_bytes=40,
        hard_limit_bytes=50,
        min_free_bytes=10,
        log_retention_days=14,
    )


def _hard_snapshot() -> StorageSnapshot:
    return StorageSnapshot(total_bytes=60, used_bytes=50, free_bytes=10)


class _Adapter:
    def __init__(self, reclaimed_by_id: dict[str, int]) -> None:
        self.reclaimed_by_id = reclaimed_by_id
        self.actions: list[CleanupAction] = []

    def reclaim(self, action: CleanupAction) -> int:
        self.actions.append(action)
        return self.reclaimed_by_id.get(action.target.target_id, 0)


def test_normal_pressure_builds_no_cleanup_plan() -> None:
    plan = build_cleanup_plan(
        StorageSnapshot(total_bytes=60, used_bytes=30, free_bytes=20),
        _budget(),
        (CleanupTarget("cache", StorageClass.BUILD_CACHE, 10),),
        max_reclaim_bytes=10,
    )
    assert plan.pressure == "normal"
    assert plan.actions == ()


def test_plan_never_contains_protected_storage_classes() -> None:
    inventory = tuple(
        CleanupTarget(storage_class.value, storage_class, 5)
        for storage_class in (
            StorageClass.PRODUCTION_STATE,
            StorageClass.EVIDENCE,
            StorageClass.ROLLBACK,
            StorageClass.BACKUP,
        )
    ) + (
        CleanupTarget("cache", StorageClass.BUILD_CACHE, 5),
    )
    plan = build_cleanup_plan(
        _hard_snapshot(),
        _budget(),
        inventory,
        max_reclaim_bytes=20,
    )
    assert tuple(action.target.storage_class for action in plan.actions) == (StorageClass.BUILD_CACHE,)


def test_logs_must_be_expired_before_becoming_cleanup_actions() -> None:
    plan = build_cleanup_plan(
        _hard_snapshot(),
        _budget(),
        (
            CleanupTarget("young-log", StorageClass.APPLICATION_LOG, 5, age_days=13),
            CleanupTarget("old-log", StorageClass.APPLICATION_LOG, 7, age_days=14),
        ),
        max_reclaim_bytes=20,
    )
    assert [action.target.target_id for action in plan.actions] == ["old-log"]
    assert plan.actions[0].operation is CleanupOperation.ROTATE_EXPIRED_LOGS


def test_plan_is_bounded_by_bytes_and_action_count() -> None:
    plan = build_cleanup_plan(
        _hard_snapshot(),
        _budget(),
        (
            CleanupTarget("cache-a", StorageClass.BUILD_CACHE, 8),
            CleanupTarget("cache-b", StorageClass.BUILD_CACHE, 8),
            CleanupTarget("tmp", StorageClass.TEMPORARY, 8),
        ),
        max_reclaim_bytes=10,
        max_actions=2,
    )
    assert len(plan.actions) == 2
    assert [action.reclaim_limit_bytes for action in plan.actions] == [8, 2]
    assert plan.planned_reclaim_bytes == 10


def test_duplicate_target_ids_fail_closed() -> None:
    with pytest.raises(ValueError, match="duplicate cleanup target_id"):
        build_cleanup_plan(
            _hard_snapshot(),
            _budget(),
            (
                CleanupTarget("same", StorageClass.BUILD_CACHE, 5),
                CleanupTarget("same", StorageClass.TEMPORARY, 5),
            ),
            max_reclaim_bytes=10,
        )


def test_executor_rejects_protected_or_mismatched_manual_actions() -> None:
    protected = CleanupAction(
        target=CleanupTarget("db", StorageClass.PRODUCTION_STATE, 5),
        operation=CleanupOperation.PRUNE_BUILD_CACHE,
        reclaim_limit_bytes=5,
    )
    plan = CleanupPlan("hard", (protected,), 5)
    with pytest.raises(ValueError, match="protected or unsupported"):
        execute_cleanup(plan, _Adapter({"db": 0}))

    mismatched = CleanupAction(
        target=CleanupTarget("tmp", StorageClass.TEMPORARY, 5),
        operation=CleanupOperation.PRUNE_BUILD_CACHE,
        reclaim_limit_bytes=5,
    )
    with pytest.raises(ValueError, match="does not match"):
        execute_cleanup(CleanupPlan("hard", (mismatched,), 5), _Adapter({"tmp": 0}))


def test_executor_enforces_per_action_and_total_byte_caps() -> None:
    action = CleanupAction(
        target=CleanupTarget("cache", StorageClass.BUILD_CACHE, 5),
        operation=CleanupOperation.PRUNE_BUILD_CACHE,
        reclaim_limit_bytes=5,
    )
    with pytest.raises(ValueError, match="exceeded action reclaim limit"):
        execute_cleanup(CleanupPlan("hard", (action,), 5), _Adapter({"cache": 6}))


def test_executor_records_bounded_results_and_verification() -> None:
    plan = build_cleanup_plan(
        _hard_snapshot(),
        _budget(),
        (
            CleanupTarget("cache", StorageClass.BUILD_CACHE, 6),
            CleanupTarget("tmp", StorageClass.TEMPORARY, 4),
        ),
        max_reclaim_bytes=10,
    )
    adapter = _Adapter({"cache": 6, "tmp": 4})
    results = execute_cleanup(plan, adapter)
    assert sum(result.reclaimed_bytes for result in results) == 10
    assert verify_cleanup(
        _hard_snapshot(),
        StorageSnapshot(total_bytes=60, used_bytes=40, free_bytes=20),
        results,
    ) is True
    assert verify_cleanup(
        _hard_snapshot(),
        StorageSnapshot(total_bytes=60, used_bytes=50, free_bytes=10),
        results,
    ) is False
