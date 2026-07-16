from __future__ import annotations

from pathlib import Path

from scripts.ci_runtime_state import (
    collect_runtime_state_targets,
    execution_safety_violations,
    reset_runtime_state,
)


def _safe_environment(tmp_path: Path) -> dict[str, str]:
    return {
        "GITHUB_ACTIONS": "true",
        "GITHUB_WORKSPACE": str(tmp_path),
        "DATABASE_URL": f"sqlite:///{tmp_path / 'project.db'}",
        "AUTONOMOUS_PAPER_STATE_FILE": str(tmp_path / "paper.json"),
        "VIRTUAL_ACCOUNT_STATE_FILE": str(tmp_path / "virtual.json"),
        "MARKET_STREAM_STATE_FILE": str(tmp_path / "market.json"),
        "TESTNET_BRIDGE_STATE_FILE": str(tmp_path / "bridge.json"),
        "EXECUTION_JOURNAL_FILE": str(tmp_path / "journal.json"),
        "SHARIPOVAI_DATA_DIR": str(tmp_path / ".ci-data"),
        "EXECUTION_KILL_SWITCH": "1",
        "TESTNET_EXECUTION_ENABLED": "0",
        "EXCHANGE_LIVE_TRADING_ENABLED": "0",
        "AUTONOMOUS_TESTNET_ENABLED": "0",
        "AUTONOMOUS_TESTNET_BRIDGE_ENABLED": "0",
        "FEATURE_BYBIT_PRIVATE_ORDER_WS": "0",
        "RUNTIME_FILL_HARVESTER_ENABLED": "0",
        "SCHEDULED_CAMPAIGN_ORCHESTRATOR_ENABLED": "0",
        "EXCHANGE_MODE": "sandbox",
        "EXCHANGE_BASE_URL": "https://api-testnet.bybit.com",
        "PHASE6_TESTNET_RELEASE_GATE": "blocked",
    }


def test_collect_targets_includes_sqlite_sidecars_without_discovery(tmp_path: Path) -> None:
    environment = _safe_environment(tmp_path)

    targets = collect_runtime_state_targets(environment, workspace=tmp_path)
    paths = {target.path for target in targets}

    database = str((tmp_path / "project.db").resolve())
    assert database in paths
    assert f"{database}-journal" in paths
    assert f"{database}-shm" in paths
    assert f"{database}-wal" in paths
    assert str((tmp_path / "paper.json").resolve()) in paths
    assert str((tmp_path / ".coverage").resolve()) in paths


def test_dry_run_never_removes_runtime_state(tmp_path: Path) -> None:
    environment = _safe_environment(tmp_path)
    database = tmp_path / "project.db"
    database.write_text("state", encoding="utf-8")

    report = reset_runtime_state(environment, workspace=tmp_path, apply=False)

    assert report.status == "ok"
    assert report.apply is False
    assert report.removed == ()
    assert database.read_text(encoding="utf-8") == "state"


def test_apply_removes_only_explicit_safe_targets(tmp_path: Path) -> None:
    environment = _safe_environment(tmp_path)
    configured_files = [
        tmp_path / "project.db",
        tmp_path / "project.db-wal",
        tmp_path / "paper.json",
        tmp_path / "virtual.json",
        tmp_path / "market.json",
        tmp_path / "bridge.json",
        tmp_path / "journal.json",
        tmp_path / ".coverage",
    ]
    for path in configured_files:
        path.write_text("state", encoding="utf-8")
    data_directory = tmp_path / ".ci-data"
    data_directory.mkdir()
    (data_directory / "runtime.json").write_text("state", encoding="utf-8")
    unrelated = tmp_path / "keep-me.txt"
    unrelated.write_text("important", encoding="utf-8")

    report = reset_runtime_state(environment, workspace=tmp_path, apply=True)

    assert report.status == "ok"
    assert report.apply is True
    assert report.authorized is True
    assert all(not path.exists() for path in configured_files)
    assert not data_directory.exists()
    assert unrelated.read_text(encoding="utf-8") == "important"


def test_apply_is_blocked_outside_workspace_or_tmp(tmp_path: Path) -> None:
    environment = _safe_environment(tmp_path)
    environment["EXECUTION_JOURNAL_FILE"] = "/var/lib/sharipovai/execution.json"

    report = reset_runtime_state(environment, workspace=tmp_path, apply=True)

    assert report.status == "blocked"
    assert any("unsafe reset target rejected" in item for item in report.violations)
    assert report.removed == ()


def test_apply_requires_explicit_ci_authority(tmp_path: Path) -> None:
    environment = _safe_environment(tmp_path)
    environment.pop("GITHUB_ACTIONS")

    report = reset_runtime_state(environment, workspace=tmp_path, apply=True)

    assert report.status == "blocked"
    assert report.authorized is False
    assert any("requires GITHUB_ACTIONS=true" in item for item in report.violations)


def test_execution_safety_audit_rejects_trading_authority(tmp_path: Path) -> None:
    environment = _safe_environment(tmp_path)
    environment.update(
        {
            "EXECUTION_KILL_SWITCH": "0",
            "TESTNET_EXECUTION_ENABLED": "1",
            "EXCHANGE_LIVE_TRADING_ENABLED": "1",
            "EXCHANGE_MODE": "live",
            "EXCHANGE_BASE_URL": "https://api.bybit.com",
            "PHASE6_TESTNET_RELEASE_GATE": "green",
        }
    )

    violations = execution_safety_violations(environment)

    assert "EXECUTION_KILL_SWITCH must remain enabled" in violations
    assert "TESTNET_EXECUTION_ENABLED must be disabled" in violations
    assert "EXCHANGE_LIVE_TRADING_ENABLED must be disabled" in violations
    assert "EXCHANGE_MODE must be sandbox or testnet" in violations
    assert "production Bybit base URL is forbidden in CI" in violations
    assert "PHASE6_TESTNET_RELEASE_GATE must not be green in CI" in violations
