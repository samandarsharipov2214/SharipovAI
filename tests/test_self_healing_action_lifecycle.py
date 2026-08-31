from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import importlib.util
import json
from pathlib import Path
import sys


MODULE_PATH = Path(__file__).resolve().parents[1] / "tools" / "self_healing_agent.py"
SPEC = importlib.util.spec_from_file_location("self_healing_action_lifecycle", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
agent = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = agent
SPEC.loader.exec_module(agent)


def _config(tmp_path: Path) -> agent.Config:
    data = tmp_path / "data"
    work = data / ".self_healing"
    repo = tmp_path / "repo"
    data.mkdir()
    repo.mkdir()
    return agent.Config(
        repo_dir=repo,
        data_dir=data,
        work_dir=work,
        log_file=data / "agent.log",
        state_file=work / "state.json",
        lock_file=work / "agent.lock",
        host_status_file=work / "container_status.json",
        host_logs_file=work / "docker_logs_15m.log",
        action_file=work / "action",
        action_meta_file=work / "action.json",
        expected_sha_file=work / "expected_sha",
        db_path=data / "db.sqlite3",
        backup_path=tmp_path / "latest.tar.gz",
        restore_candidate=work / "restore_candidate.db",
        health_url="http://127.0.0.1:1/health",
        websocket_url="http://127.0.0.1:1/ws",
        request_timeout_seconds=0.1,
        pytest_timeout_seconds=10,
        websocket_alert_after_seconds=300,
        alert_cooldown_seconds=3600,
        restart_cooldown_seconds=1800,
        max_related_tests=25,
        max_log_bytes=1024,
    )


def _request(config: agent.Config, action: str = "restart_sharipovai") -> str:
    request = agent.ActionRequest(config, agent.build_logger(config.log_file))
    request.request(action, "synthetic health failure")
    request.persist()
    return json.loads(config.action_meta_file.read_text(encoding="utf-8"))["generation"]


def test_failed_action_is_terminal_and_never_replayed(tmp_path: Path) -> None:
    config = _config(tmp_path)
    generation = _request(config)
    claimed = agent.claim_noncritical_action(config)
    assert claimed is not None and claimed["generation"] == generation

    assert agent.terminalize_noncritical_action(config, generation, "failed", "exit 1")
    assert agent.claim_noncritical_action(config) is None
    assert not config.action_file.exists()
    assert not agent.action_claim_path(config).exists()
    result = json.loads(agent.action_result_path(config, generation).read_text(encoding="utf-8"))
    assert result["status"] == "failed"


def test_successful_action_is_terminal_and_never_replayed(tmp_path: Path) -> None:
    config = _config(tmp_path)
    generation = _request(config, "restart_caddy")
    assert agent.claim_noncritical_action(config) is not None
    assert agent.terminalize_noncritical_action(config, generation, "success", "verified")
    assert agent.claim_noncritical_action(config) is None


def test_new_cycle_gets_new_generation_and_each_executes_once(tmp_path: Path) -> None:
    config = _config(tmp_path)
    first = _request(config)
    assert agent.claim_noncritical_action(config) is not None
    assert agent.terminalize_noncritical_action(config, first, "failed", "first failure")

    second = _request(config)
    assert second != first
    claimed = agent.claim_noncritical_action(config)
    assert claimed is not None and claimed["generation"] == second
    assert agent.terminalize_noncritical_action(config, second, "success", "second verified")


def test_same_generation_cannot_execute_twice(tmp_path: Path) -> None:
    config = _config(tmp_path)
    generation = _request(config)
    metadata = config.action_meta_file.read_text(encoding="utf-8")
    assert agent.claim_noncritical_action(config) is not None
    assert agent.terminalize_noncritical_action(config, generation, "success", "verified")

    config.action_meta_file.write_text(metadata, encoding="utf-8")
    config.action_file.write_text("restart_sharipovai\n", encoding="utf-8")
    assert agent.claim_noncritical_action(config) is None
    assert not config.action_file.exists()


def test_concurrent_readers_allow_exactly_one_claim(tmp_path: Path) -> None:
    config = _config(tmp_path)
    generation = _request(config)

    with ThreadPoolExecutor(max_workers=8) as executor:
        claims = list(executor.map(lambda _: agent.claim_noncritical_action(config), range(8)))

    claimed = [claim for claim in claims if claim is not None]
    assert len(claimed) == 1
    assert claimed[0]["generation"] == generation
    assert agent.terminalize_noncritical_action(config, generation, "success", "verified")


def test_legacy_stale_action_cannot_override_new_cycle(tmp_path: Path) -> None:
    config = _config(tmp_path)
    config.work_dir.mkdir(parents=True)
    config.action_file.write_text("restart_sharipovai\n", encoding="utf-8")
    config.action_meta_file.write_text(
        json.dumps({"action": "restart_sharipovai", "created_at": "old"}),
        encoding="utf-8",
    )
    rejected = agent.reject_stale_noncritical_authority(config)
    assert rejected and rejected.startswith("legacy-")
    assert not config.action_file.exists()

    current = _request(config)
    claimed = agent.claim_noncritical_action(config)
    assert claimed is not None and claimed["generation"] == current


def test_host_crash_after_claim_is_rejected_without_replay(tmp_path: Path) -> None:
    config = _config(tmp_path)
    generation = _request(config)
    assert agent.claim_noncritical_action(config) is not None

    assert agent.reject_stale_noncritical_authority(config) == generation
    assert agent.claim_noncritical_action(config) is None
    result = json.loads(agent.action_result_path(config, generation).read_text(encoding="utf-8"))
    assert result["status"] == "rejected"


def test_host_crash_before_claim_is_rejected_without_replay(tmp_path: Path) -> None:
    config = _config(tmp_path)
    generation = _request(config)

    assert agent.reject_stale_noncritical_authority(config) == generation
    assert agent.claim_noncritical_action(config) is None
    result = json.loads(agent.action_result_path(config, generation).read_text(encoding="utf-8"))
    assert result["status"] == "rejected"


def test_none_cycle_does_not_erase_active_claim(tmp_path: Path) -> None:
    config = _config(tmp_path)
    generation = _request(config)
    assert agent.claim_noncritical_action(config) is not None
    claim_before = agent.action_claim_path(config).read_bytes()

    agent.ActionRequest(config, agent.build_logger(config.log_file)).persist()

    assert agent.action_claim_path(config).read_bytes() == claim_before
    assert json.loads(claim_before)["generation"] == generation


def test_critical_action_artifact_is_not_claimed_by_noncritical_lifecycle(tmp_path: Path) -> None:
    config = _config(tmp_path)
    config.work_dir.mkdir(parents=True)
    config.action_file.write_text("restore_database\n", encoding="utf-8")
    config.action_meta_file.write_text(
        json.dumps({"action": "restore_database", "approval_decision_id": "dcc-1"}),
        encoding="utf-8",
    )

    assert agent.reject_stale_noncritical_authority(config) is None
    assert agent.claim_noncritical_action(config) is None
    assert config.action_file.read_text(encoding="utf-8").strip() == "restore_database"


def test_wrapper_terminalizes_noncritical_failure_instead_of_leaving_pending() -> None:
    wrapper = (MODULE_PATH.parents[1] / "deploy" / "vps" / "self-healing-run.sh").read_text(
        encoding="utf-8"
    )
    assert "terminalize_noncritical_action failed" in wrapper
    assert "failed and was left pending for inspection" not in wrapper
