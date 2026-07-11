from tools.supervisor_policy import ServicePolicy


def test_cooldown_blocks_immediate_restart() -> None:
    policy = ServicePolicy(max_restarts=4, window_seconds=300, cooldown_seconds=30, quarantine_seconds=600)
    policy.record_restart(100.0)
    allowed, reason = policy.decision(110.0)
    assert allowed is False
    assert reason == "cooldown"


def test_restart_budget_enters_quarantine() -> None:
    policy = ServicePolicy(max_restarts=2, window_seconds=300, cooldown_seconds=0, quarantine_seconds=600)
    policy.record_restart(100.0)
    policy.record_restart(110.0)
    allowed, reason = policy.decision(120.0)
    assert allowed is False
    assert reason == "quarantined"
    assert policy.quarantined_until == 720.0


def test_healthy_state_clears_failures() -> None:
    policy = ServicePolicy(max_restarts=1, cooldown_seconds=0)
    policy.record_restart(100.0)
    policy.decision(101.0)
    policy.record_healthy()
    allowed, reason = policy.decision(102.0)
    assert allowed is True
    assert reason == "allowed"
