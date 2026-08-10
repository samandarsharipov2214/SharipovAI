from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys
import tarfile
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "tools" / "self_healing_agent.py"
SPEC = importlib.util.spec_from_file_location("sharipovai_self_healing_agent", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
agent = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = agent
SPEC.loader.exec_module(agent)


def make_config(tmp_path: Path) -> agent.Config:
    data = tmp_path / "data"
    work = data / ".self_healing"
    repo = tmp_path / "repo"
    repo.mkdir()
    data.mkdir()
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
        db_path=data / "sharipovai_shared.db",
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
        max_log_bytes=1024 * 1024,
    )


def create_db(path: Path, value: int = 1) -> None:
    with sqlite3.connect(path) as connection:
        connection.execute("create table if not exists t (x integer)")
        connection.execute("insert into t values (?)", (value,))


def test_sqlite_integrity_ok_and_corrupt(tmp_path: Path) -> None:
    valid = tmp_path / "valid.db"
    create_db(valid)
    assert agent.sqlite_integrity(valid) == "ok"

    corrupt = tmp_path / "corrupt.db"
    corrupt.write_bytes(b"not sqlite")
    assert agent.sqlite_integrity(corrupt) != "ok"


def test_prepare_restore_candidate(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    source_db = tmp_path / "source.db"
    create_db(source_db, 42)
    with tarfile.open(config.backup_path, "w:gz") as archive:
        archive.add(source_db, arcname="runtime/sharipovai_shared.db")

    instance = agent.SelfHealingAgent(config)
    info = instance.prepare_restore_candidate()

    assert config.restore_candidate.is_file()
    assert agent.sqlite_integrity(config.restore_candidate) == "ok"
    assert info["database_member"] == "runtime/sharipovai_shared.db"
    assert len(info["candidate_sha256"]) == 64


def test_action_priority_and_persistence(tmp_path: Path, monkeypatch) -> None:
    config = make_config(tmp_path)
    logger = agent.build_logger(config.log_file)
    action = agent.ActionRequest(config, logger)
    action.request("restart_caddy", "caddy")
    action.request("compose_up", "stack")
    action.request("restart_sharipovai", "app")
    assert action.action == "restart_sharipovai"
    action.request("restore_database", "db")
    monkeypatch.setattr(action, "_request_critical_owner_approval", lambda: None)
    action.persist()

    assert not config.action_file.exists()


def test_extract_error_excerpts() -> None:
    text = (
        "INFO ok\nERROR boom\nline 1\n"
        "Traceback (most recent call last):\nValueError: bad\n"
    )
    excerpts = agent.extract_error_excerpts(text)
    assert excerpts
    assert "ERROR boom" in "\n".join(excerpts)
    assert "Traceback" in "\n".join(excerpts)


def test_discover_related_tests(tmp_path: Path) -> None:
    (tmp_path / "tests").mkdir()
    (tmp_path / "dashboard" / "tests").mkdir(parents=True)
    (tmp_path / "tests" / "test_market.py").write_text(
        "from exchange_connector.bybit_websocket_worker import BybitWebSocketWorker\n"
    )
    (tmp_path / "dashboard" / "tests" / "test_dashboard.py").write_text(
        "from dashboard.routes import ai_bots_api\n"
    )
    selected = agent.discover_related_tests(
        tmp_path,
        {"exchange_connector/bybit_websocket_worker.py"},
        max_tests=25,
    )
    assert "tests/test_market.py" in selected


def test_deploy_change_selects_production_audit(tmp_path: Path) -> None:
    (tmp_path / "tests").mkdir()
    audit = tmp_path / "tests" / "test_phase11_production_audit.py"
    audit.write_text("def test_audit(): pass\n")
    selected = agent.discover_related_tests(
        tmp_path,
        {"deploy/vps/docker-compose.yml"},
        max_tests=25,
    )
    assert "tests/test_phase11_production_audit.py" in selected


def test_repository_snapshot_keeps_git_metadata(tmp_path: Path) -> None:
    source = tmp_path / "source"
    destination = tmp_path / "destination"
    (source / ".git").mkdir(parents=True)
    (source / ".git" / "HEAD").write_text("ref: refs/heads/main\n")
    (source / "module.py").write_text("VALUE = 1\n")

    agent.copy_repository_snapshot(source, destination)

    assert (destination / ".git" / "HEAD").is_file()
    assert (destination / "module.py").is_file()
