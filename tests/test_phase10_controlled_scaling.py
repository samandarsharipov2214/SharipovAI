from __future__ import annotations

import threading
from datetime import datetime, timezone

import pytest

from campaigns.phase10_scaling import ControlledScalingService, ScalingExecutionPolicy
from storage import ProjectDatabase


def _database(tmp_path):
    return ProjectDatabase(f"sqlite:///{tmp_path / 'phase10.db'}")


def _plan(**overrides):
    plan = {
        "plan_id": "p9s_test",
        "status": "eligible_for_manual_scaling_review",
        "failed_gates": [],
        "gates": {"all_source_gates_clean": True},
        "campaign_ids": ["c1", "c2"],
        "current_notional_usdt": 25,
        "proposed_next_notional_usdt": 37.5,
        "evidence": {"maximum_drawdown_bps": 100},
    }
    plan.update(overrides)
    return plan


def _activate(service, *, actor="owner", now_ms=1000):
    return service.activate(
        _plan(),
        actor=actor,
        confirmation="I_APPROVE_CONTROLLED_TESTNET_NOTIONAL_SCALING",
        now_ms=now_ms,
    )


def test_activation_is_integrity_protected_and_survives_restart(tmp_path):
    database = _database(tmp_path)
    service = ControlledScalingService(
        database,
        policy=ScalingExecutionPolicy(activation_ttl_seconds=60),
    )
    activation = _activate(service)
    restarted = ControlledScalingService(
        _database(tmp_path),
        policy=ScalingExecutionPolicy(activation_ttl_seconds=60),
    )
    result = restarted.validate_authority(
        activation["activation_id"],
        scope="BTCUSDT",
        requested_notional_usdt=37.5,
        now_ms=2000,
    )
    assert result["allowed"] is True
    assert all(result["checks"].values())
    assert activation["mainnet_enabled"] is False
    assert activation["kill_switch_override"] is False


def test_expired_revoked_and_non_finite_authority_fail_closed(tmp_path):
    service = ControlledScalingService(
        _database(tmp_path),
        policy=ScalingExecutionPolicy(activation_ttl_seconds=60),
    )
    activation = _activate(service)
    assert service.validate_authority(
        activation["activation_id"],
        scope="BTCUSDT",
        requested_notional_usdt=float("nan"),
        now_ms=2000,
    )["allowed"] is False
    expired = service.validate_authority(
        activation["activation_id"],
        scope="BTCUSDT",
        requested_notional_usdt=10,
        now_ms=61001,
    )
    assert expired["allowed"] is False
    assert "not_expired" in expired["failed_checks"]
    service.revoke(
        activation["activation_id"],
        actor="owner",
        reason="campaign closed",
        now_ms=62000,
    )
    revoked = service.validate_authority(
        activation["activation_id"],
        scope="BTCUSDT",
        requested_notional_usdt=10,
        now_ms=62001,
    )
    assert revoked["allowed"] is False
    assert "active" in revoked["failed_checks"]


@pytest.mark.parametrize(
    "field,value",
    [
        ("current_notional_usdt", float("nan")),
        ("current_notional_usdt", float("inf")),
        ("proposed_next_notional_usdt", float("nan")),
        ("proposed_next_notional_usdt", float("inf")),
    ],
)
def test_activation_rejects_non_finite_plan_numbers(tmp_path, field, value):
    service = ControlledScalingService(_database(tmp_path))
    with pytest.raises(ValueError, match="finite"):
        service.activate(
            _plan(**{field: value}),
            actor="owner",
            confirmation="I_APPROVE_CONTROLLED_TESTNET_NOTIONAL_SCALING",
        )


def test_tampered_authority_and_lock_mismatch_fail_closed(tmp_path):
    database = _database(tmp_path)
    service = ControlledScalingService(database)
    activation = _activate(service)
    row = database.get_json("phase10_scaling_activations", activation["activation_id"])
    tampered = dict(row["value"])
    tampered["authorized_notional_usdt"] = 49
    database.put_json(
        "phase10_scaling_activations",
        activation["activation_id"],
        tampered,
        expected_version=row["version"],
    )
    result = service.validate_authority(
        activation["activation_id"],
        scope="BTCUSDT",
        requested_notional_usdt=10,
        now_ms=2000,
    )
    assert result["allowed"] is False
    assert "integrity" in result["failed_checks"]


def test_parallel_activation_allows_only_one_global_authority(tmp_path):
    database_url = f"sqlite:///{tmp_path / 'race.db'}"
    successes = []
    failures = []
    barrier = threading.Barrier(2)

    def worker(actor):
        try:
            service = ControlledScalingService(ProjectDatabase(database_url))
            barrier.wait(timeout=5)
            successes.append(_activate(service, actor=actor, now_ms=1000))
        except Exception as exc:  # the losing activation must fail closed
            failures.append(exc)

    threads = [threading.Thread(target=worker, args=(f"owner-{index}",)) for index in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)
    assert all(not thread.is_alive() for thread in threads)
    assert len(successes) == 1
    assert len(failures) == 1
    assert isinstance(failures[0], (ValueError, RuntimeError))


def test_monthly_reports_are_immutable_idempotent_and_retain_history(tmp_path):
    service = ControlledScalingService(_database(tmp_path))
    july_1 = int(datetime(2026, 7, 1, tzinfo=timezone.utc).timestamp() * 1000)
    july_2 = int(datetime(2026, 7, 2, tzinfo=timezone.utc).timestamp() * 1000)
    july_3 = int(datetime(2026, 7, 3, tzinfo=timezone.utc).timestamp() * 1000)
    first = service.record_snapshot(
        {
            "campaign_id": "c1",
            "net_pnl_usdt": -1.5,
            "fees_usdt": 0.2,
            "matched_fill_count": 20,
            "maximum_drawdown_bps": 100,
        },
        captured_at_ms=july_1,
    )
    second = service.record_snapshot(
        {
            "campaign_id": "c2",
            "net_pnl_usdt": 2.5,
            "fees_usdt": 0.3,
            "matched_fill_count": 20,
            "maximum_drawdown_bps": 120,
        },
        captured_at_ms=july_2,
    )
    report = service.monthly_report([first, second], month="2026-07", generated_at_ms=july_3)
    repeated = service.monthly_report([second, first], month="2026-07", generated_at_ms=july_3 + 1)
    assert repeated["report_id"] == report["report_id"]
    assert report["net_pnl_usdt"] == 1.0
    assert report["matched_fill_count"] == 40
    assert len(service.list_monthly_reports()) == 1

    third = service.record_snapshot(
        {
            "campaign_id": "c3",
            "net_pnl_usdt": -5,
            "fees_usdt": 0.4,
            "matched_fill_count": 20,
            "maximum_drawdown_bps": 300,
        },
        captured_at_ms=july_3,
    )
    changed = service.monthly_report([first, second, third], month="2026-07", generated_at_ms=july_3 + 2)
    assert changed["report_id"] != report["report_id"]
    assert changed["drawdown_alert"] is True
    reports = service.list_monthly_reports()
    assert {item["report_id"] for item in reports} == {report["report_id"], changed["report_id"]}


def test_conflicting_or_corrupt_snapshot_blocks_monthly_report(tmp_path):
    service = ControlledScalingService(_database(tmp_path))
    captured = int(datetime(2026, 7, 1, tzinfo=timezone.utc).timestamp() * 1000)
    snapshot = service.record_snapshot(
        {
            "campaign_id": "c1",
            "net_pnl_usdt": 1,
            "fees_usdt": 0.1,
            "matched_fill_count": 20,
            "maximum_drawdown_bps": 10,
        },
        captured_at_ms=captured,
    )
    corrupt = dict(snapshot)
    corrupt["metrics"] = {**snapshot["metrics"], "net_pnl_usdt": 999}
    with pytest.raises(ValueError, match="integrity"):
        service.monthly_report([corrupt], month="2026-07")
