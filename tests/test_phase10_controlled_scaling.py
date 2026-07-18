from campaigns.phase10_scaling import ControlledScalingService, ScalingExecutionPolicy
from storage import ProjectDatabase


def _database(tmp_path):
    return ProjectDatabase(f"sqlite:///{tmp_path / 'phase10.db'}")


def _plan():
    return {
        "plan_id": "p9s_test",
        "status": "eligible_for_manual_scaling_review",
        "failed_gates": [],
        "campaign_ids": ["c1", "c2"],
        "current_notional_usdt": 25,
        "proposed_next_notional_usdt": 37.5,
        "evidence": {"maximum_drawdown_bps": 100},
    }


def test_activation_is_expiring_testnet_only(tmp_path):
    service = ControlledScalingService(_database(tmp_path), policy=ScalingExecutionPolicy(activation_ttl_seconds=60))
    activation = service.activate(_plan(), actor="owner", confirmation="I_APPROVE_CONTROLLED_TESTNET_NOTIONAL_SCALING", now_ms=1000)
    assert activation["authorized_notional_usdt"] == 37.5
    assert activation["mainnet_enabled"] is False
    assert activation["kill_switch_override"] is False
    assert service.validate_authority(activation["activation_id"], scope="BTCUSDT", requested_notional_usdt=37.5, now_ms=2000)["allowed"] is True
    expired = service.validate_authority(activation["activation_id"], scope="BTCUSDT", requested_notional_usdt=37.5, now_ms=61001)
    assert expired["allowed"] is False
    assert "not_expired" in expired["failed_checks"]


def test_activation_rejects_wrong_confirmation(tmp_path):
    service = ControlledScalingService(_database(tmp_path))
    try:
        service.activate(_plan(), actor="owner", confirmation="yes")
    except ValueError as exc:
        assert "exact scaling confirmation" in str(exc)
    else:
        raise AssertionError("activation must fail closed")


def test_revoke_invalidates_authority(tmp_path):
    service = ControlledScalingService(_database(tmp_path))
    activation = service.activate(_plan(), actor="owner", confirmation="I_APPROVE_CONTROLLED_TESTNET_NOTIONAL_SCALING", now_ms=1000)
    service.revoke(activation["activation_id"], actor="owner", reason="campaign closed", now_ms=2000)
    result = service.validate_authority(activation["activation_id"], scope="BTCUSDT", requested_notional_usdt=10, now_ms=3000)
    assert result["allowed"] is False
    assert "active" in result["failed_checks"]
