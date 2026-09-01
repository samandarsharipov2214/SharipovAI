from __future__ import annotations

import os
from pathlib import Path
import subprocess

from audit.phase11_production_audit import ProductionAudit

ROOT = Path(__file__).resolve().parents[1]


def _safe_environment(monkeypatch, tmp_path):
    values = {
        "DATABASE_URL": f"sqlite:///{tmp_path / 'audit.db'}",
        "SHARIPOVAI_DATABASE_REQUIRED": "1",
        "SHARIPOVAI_DISABLE_AUTH": "0",
        "AUTH_SECRET": "phase11-test-secret",
        "ADMIN_USERNAME": "phase11-test-admin",
        "ADMIN_PASSWORD": "phase11-test-password",
        "EXECUTION_KILL_SWITCH": "1",
        "EXCHANGE_MODE": "sandbox",
        "EXCHANGE_BASE_URL": "https://api-testnet.bybit.com",
        "EXCHANGE_LIVE_TRADING_ENABLED": "0",
        "FEATURE_BYBIT_LIVE_EXECUTION": "0",
        "FEATURE_BYBIT_TESTNET_EXECUTION": "0",
        "TESTNET_EXECUTION_ENABLED": "0",
        "AUTONOMOUS_TESTNET_ENABLED": "0",
        "AUTONOMOUS_TESTNET_BRIDGE_ENABLED": "0",
        "FEATURE_BYBIT_PRIVATE_ORDER_WS": "0",
        "BYBIT_ALLOW_LEGACY_EXCHANGE_CREDENTIALS": "0",
        "PHASE11_MAX_TESTNET_NOTIONAL_USDT": "50",
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    return dict(os.environ)


def _failed_checks(report):
    return [
        {
            "name": item["name"],
            "severity": item["severity"],
            "evidence": item["evidence"],
        }
        for item in report["checks"]
        if not item["passed"]
    ]


def test_full_audit_is_ready_deterministic_and_mainnet_false(
    tmp_path,
    monkeypatch,
):
    environment = _safe_environment(monkeypatch, tmp_path)
    first = ProductionAudit(ROOT, environ=environment).run()
    second = ProductionAudit(ROOT, environ=environment).run()
    assert first["blockers"] == [], _failed_checks(first)
    assert first["status"] == "ready_for_bounded_testnet_preflight"
    assert first["mainnet_enabled"] is False
    assert first["automatic_campaign_launch"] is False
    assert len(first["audit_sha256"]) == 64
    assert second["audit_sha256"] == first["audit_sha256"]
    assert second["created_at_ms"] >= first["created_at_ms"]


def test_audit_blocks_live_execution_and_invalid_notional(
    tmp_path,
    monkeypatch,
):
    environment = _safe_environment(monkeypatch, tmp_path)
    environment["EXCHANGE_LIVE_TRADING_ENABLED"] = "1"
    environment["PHASE11_MAX_TESTNET_NOTIONAL_USDT"] = "nan"
    monkeypatch.setenv("EXCHANGE_LIVE_TRADING_ENABLED", "1")
    monkeypatch.setenv("PHASE11_MAX_TESTNET_NOTIONAL_USDT", "nan")
    report = ProductionAudit(ROOT, environ=environment).run()
    assert report["status"] == "blocked"
    assert "safe_runtime_configuration" in report["blockers"]
    assert "bounded_testnet_notional" in report["blockers"]
    assert report["mainnet_enabled"] is False


def test_audit_blocks_missing_authentication_material(tmp_path, monkeypatch):
    environment = _safe_environment(monkeypatch, tmp_path)
    environment["AUTH_SECRET"] = ""
    report = ProductionAudit(ROOT, environ=environment).run()
    assert report["status"] == "blocked"
    assert "safe_runtime_configuration" in report["blockers"]
    check = next(
        item
        for item in report["checks"]
        if item["name"] == "safe_runtime_configuration"
    )
    assert check["evidence"]["authentication_enabled"] is True
    assert check["evidence"]["authentication_material_configured"] is False


def test_audit_blocks_database_failure(tmp_path, monkeypatch):
    environment = _safe_environment(monkeypatch, tmp_path)

    def failed_health(_self):
        return {
            "status": "error",
            "backend": "postgresql",
            "error": "connection failed",
        }

    monkeypatch.setattr("storage.ProjectDatabase.health", failed_health)
    report = ProductionAudit(ROOT, environ=environment).run()
    assert report["status"] == "blocked"
    assert "canonical_database_health" in report["blockers"]
    check = next(
        item
        for item in report["checks"]
        if item["name"] == "canonical_database_health"
    )
    assert check["evidence"]["error_type"] == "connection failed"


def test_audit_blocks_missing_assets_and_unverified_git(tmp_path, monkeypatch):
    environment = _safe_environment(monkeypatch, tmp_path)
    report = ProductionAudit(tmp_path, environ=environment).run()
    assert report["status"] == "blocked"
    assert "required_production_assets" in report["blockers"]
    assert "secret_file_hygiene" in report["blockers"]


def test_secret_hygiene_ignores_inherited_git_inventory(tmp_path, monkeypatch):
    audit_root = tmp_path / "audit-root"
    other_repo = tmp_path / "other-repo"
    audit_root.mkdir()
    other_repo.mkdir()
    subprocess.run(["git", "init", "-q", str(other_repo)], check=True)
    monkeypatch.setenv("GIT_DIR", str(other_repo / ".git"))
    monkeypatch.setenv("GIT_WORK_TREE", str(other_repo))
    environment = _safe_environment(monkeypatch, tmp_path)

    report = ProductionAudit(audit_root, environ=environment).run()

    check = next(
        item for item in report["checks"] if item["name"] == "secret_file_hygiene"
    )
    assert "secret_file_hygiene" in report["blockers"]
    assert check["evidence"]["git_inventory_verified"] is False


def test_secret_hygiene_does_not_walk_to_parent_repository(tmp_path, monkeypatch):
    parent_repo = tmp_path / "parent-repo"
    audit_root = parent_repo / "nested-audit-root"
    parent_repo.mkdir()
    audit_root.mkdir()
    subprocess.run(["git", "init", "-q", str(parent_repo)], check=True)
    environment = _safe_environment(monkeypatch, tmp_path)

    report = ProductionAudit(audit_root, environ=environment).run()

    check = next(
        item for item in report["checks"] if item["name"] == "secret_file_hygiene"
    )
    assert "secret_file_hygiene" in report["blockers"]
    assert check["evidence"]["git_inventory_verified"] is False


def test_secret_hygiene_blocks_real_root_secret_without_git(tmp_path, monkeypatch):
    audit_root = tmp_path / "audit-root"
    audit_root.mkdir()
    (audit_root / ".env").write_text("TEST_ONLY=not-a-secret\n", encoding="utf-8")
    environment = _safe_environment(monkeypatch, tmp_path)

    report = ProductionAudit(audit_root, environ=environment).run()

    check = next(
        item for item in report["checks"] if item["name"] == "secret_file_hygiene"
    )
    assert "secret_file_hygiene" in report["blockers"]
    assert check["evidence"]["forbidden_root_files"] == [".env"]
