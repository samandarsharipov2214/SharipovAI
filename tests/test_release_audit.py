from __future__ import annotations

import shutil
from pathlib import Path

from scripts.release_audit import _audit_blueprint, _audit_runtime_environment, audit_repository


def configure_safe_runtime(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("AUTH_SECRET", "ci-secret")
    monkeypatch.setenv("ADMIN_USERNAME", "admin")
    monkeypatch.setenv("ADMIN_PASSWORD", "password-long-enough")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'shared.db'}")
    monkeypatch.setenv("SHARIPOVAI_DATABASE_REQUIRED", "1")
    monkeypatch.setenv("SHARIPOVAI_DISABLE_AUTH", "0")
    monkeypatch.setenv("EXECUTION_KILL_SWITCH", "1")
    monkeypatch.setenv("TESTNET_EXECUTION_ENABLED", "0")
    monkeypatch.setenv("AUTONOMOUS_TESTNET_ENABLED", "0")
    monkeypatch.setenv("AUTONOMOUS_TESTNET_BRIDGE_ENABLED", "0")
    monkeypatch.setenv("EXCHANGE_LIVE_TRADING_ENABLED", "0")
    monkeypatch.setenv("FEATURE_BYBIT_PRIVATE_ORDER_WS", "0")
    monkeypatch.setenv("BYBIT_ALLOW_LEGACY_EXCHANGE_CREDENTIALS", "0")
    monkeypatch.setenv("EXCHANGE_MODE", "sandbox")
    monkeypatch.setenv("AUTONOMOUS_TRADING_STAGE", "2")
    monkeypatch.setenv("EXCHANGE_BASE_URL", "https://api-testnet.bybit.com")
    monkeypatch.setenv("EXECUTION_JOURNAL_FILE", str(tmp_path / "execution-journal.json"))
    for name in (
        "BYBIT_MAINNET_API_KEY", "BYBIT_MAINNET_API_SECRET", "BYBIT_READONLY_API_KEY",
        "BYBIT_READONLY_API_SECRET", "BYBIT_TESTNET_API_KEY", "BYBIT_TESTNET_API_SECRET",
    ):
        monkeypatch.delenv(name, raising=False)


def _copy_vps_contract(tmp_path: Path) -> Path:
    source = Path(".").resolve()
    root = tmp_path / "repo"
    deploy = root / "deploy" / "vps"
    deploy.mkdir(parents=True)
    for name in ("docker-compose.yml", "Caddyfile", "update_from_main.sh"):
        shutil.copy2(source / "deploy" / "vps" / name, deploy / name)
    shutil.copy2(source / "Dockerfile", root / "Dockerfile")
    return root


def test_current_repository_release_audit_passes(monkeypatch, tmp_path: Path) -> None:
    configure_safe_runtime(monkeypatch, tmp_path)
    report = audit_repository(Path("."), runtime=True)
    assert report.status == "ok", report.errors
    assert any(item.name == "canonical_ai_organs" and item.status == "pass" for item in report.checks)
    assert any(item.name == "execution_journal_database" and item.status == "pass" for item in report.checks)


def test_unsafe_vps_testnet_value_is_detected(tmp_path: Path) -> None:
    root = _copy_vps_contract(tmp_path)
    compose_path = root / "deploy" / "vps" / "docker-compose.yml"
    source = compose_path.read_text(encoding="utf-8")
    compose_path.write_text(source.replace('TESTNET_EXECUTION_ENABLED: "0"', 'TESTNET_EXECUTION_ENABLED: "1"', 1), encoding="utf-8")
    seen = {}

    def record(name, passed, detail, **kwargs):
        seen[name] = (passed, detail)

    _audit_blueprint(root, record)
    assert seen["vps_testnet_locked"][0] is False


def test_enabled_vps_bridge_is_detected(tmp_path: Path) -> None:
    root = _copy_vps_contract(tmp_path)
    compose_path = root / "deploy" / "vps" / "docker-compose.yml"
    source = compose_path.read_text(encoding="utf-8")
    compose_path.write_text(source.replace('AUTONOMOUS_TESTNET_BRIDGE_ENABLED: "0"', 'AUTONOMOUS_TESTNET_BRIDGE_ENABLED: "1"', 1), encoding="utf-8")
    seen = {}

    def record(name, passed, detail, **kwargs):
        seen[name] = passed

    _audit_blueprint(root, record)
    assert seen["vps_testnet_locked"] is False


def test_missing_runtime_auth_kill_switch_and_enabled_live_are_blocked(monkeypatch) -> None:
    for name in ("AUTH_SECRET", "ADMIN_USERNAME", "ADMIN_PASSWORD", "DATABASE_URL", "EXECUTION_KILL_SWITCH"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("SHARIPOVAI_DISABLE_AUTH", "1")
    monkeypatch.setenv("EXCHANGE_LIVE_TRADING_ENABLED", "1")
    monkeypatch.setenv("EXCHANGE_MODE", "live")
    monkeypatch.setenv("AUTONOMOUS_TRADING_STAGE", "4")
    seen = {}

    def record(name, passed, detail, **kwargs):
        seen[name] = passed

    _audit_runtime_environment(record)
    assert seen["runtime_required_configuration"] is False
    assert seen["runtime_auth_enabled"] is False
    assert seen["runtime_kill_switch"] is False
    assert seen["runtime_live_locked"] is False
    assert seen["runtime_exchange_sandbox"] is False
    assert seen["runtime_stage_safe"] is False


def test_partial_credentials_and_mainnet_credentials_are_blocked(monkeypatch) -> None:
    monkeypatch.setenv("BYBIT_TESTNET_API_KEY", "only-key")
    monkeypatch.delenv("BYBIT_TESTNET_API_SECRET", raising=False)
    monkeypatch.setenv("BYBIT_MAINNET_API_KEY", "live-key")
    monkeypatch.setenv("BYBIT_MAINNET_API_SECRET", "live-secret")
    monkeypatch.delenv("RELEASE_AUDIT_ALLOW_MAINNET_CREDENTIALS", raising=False)
    seen = {}

    def record(name, passed, detail, **kwargs):
        seen[name] = passed

    _audit_runtime_environment(record)
    assert seen["runtime_bybit_testnet_pair"] is False
    assert seen["runtime_mainnet_credentials_absent"] is False
