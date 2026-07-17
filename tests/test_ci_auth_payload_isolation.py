from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_complete_pytest_workflows_use_explicit_payload_test_mode() -> None:
    for name in ("ci.yml", "tests.yml"):
        source = _read(WORKFLOWS / name)
        assert "SHARIPOVAI_DISABLE_AUTH: '1'" in source, name
        assert "ADMIN_USERNAME:" in source, name
        assert "ADMIN_PASSWORD:" in source, name
        assert "AUTH_SECRET:" in source, name
        assert "EXECUTION_KILL_SWITCH: '1'" in source, name
        assert "TESTNET_EXECUTION_ENABLED: '0'" in source, name
        assert "EXCHANGE_LIVE_TRADING_ENABLED: '0'" in source, name


def test_auth_contract_explicitly_restores_production_auth() -> None:
    source = _read(ROOT / "dashboard" / "tests" / "test_canonical_agent_health.py")
    assert "test_agent_health_api_requires_auth_by_default" in source
    assert 'monkeypatch.delenv("SHARIPOVAI_DISABLE_AUTH", raising=False)' in source
    assert "assert response.status_code == 401" in source


def test_temporary_auth_diagnostic_workflow_is_absent() -> None:
    assert not (WORKFLOWS / "pr195-auth-diagnostic.yml").exists()
