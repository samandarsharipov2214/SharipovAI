from __future__ import annotations

from pathlib import Path


RUNNER = Path(__file__).resolve().parents[1] / "deploy" / "vps" / "self-healing-run.sh"


def test_critical_self_healing_actions_fail_closed_without_owner_approval() -> None:
    script = RUNNER.read_text(encoding="utf-8")

    guard = script.index('restore_database|git_revert)')
    execution = script.index('restore_database)\n            log "Executing allow-listed action: restore_database"')
    assert guard < execution
    assert "critical_action_is_owner_approved" in script
    assert 'decision.status != "approved"' in script
    assert 'decision.proposal.get("critical_action") != action' in script
    assert 'decision.owner_actor_id != owner_id' in script
    assert 'decision.owner_chat_id != owner_id' in script


def test_restart_and_compose_actions_remain_automatic() -> None:
    script = RUNNER.read_text(encoding="utf-8")

    critical_guard = script[script.index("execute_action() {"):script.index('case "$action" in', script.index("execute_action() {") + 1)]
    assert "compose_up" not in critical_guard
    assert "restart_sharipovai" not in critical_guard
