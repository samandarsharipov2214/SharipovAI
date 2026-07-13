from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
AGENT = ROOT / "deploy" / "vps" / "remote_agent.sh"


def text() -> str:
    return AGENT.read_text(encoding="utf-8")


def test_remote_agent_shell_syntax() -> None:
    bash = shutil.which("bash")
    if bash is None:
        pytest.skip("bash is unavailable")
    result = subprocess.run([bash, "-n", str(AGENT)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_runner_recovery_is_conditional_and_targets_existing_service() -> None:
    content = text()
    assert "find_actions_runner_service" in content
    assert "/^actions\\.runner\\..*\\.service$/" in content
    assert 'systemctl is-active --quiet "${runner_service}"' in content
    assert 'systemctl restart "${runner_service}"' in content
    assert content.index('systemctl is-active --quiet "${runner_service}"') < content.index(
        'systemctl restart "${runner_service}"'
    )
    assert "systemctl enable" not in content
    assert "install_github_actions_runner.sh" not in content


def test_runner_failure_does_not_disable_application_maintenance() -> None:
    content = text()
    assert "if ! ensure_actions_runner; then" in content
    assert "runner_state='degraded'" in content
    assert "continuing application maintenance" in content
    assert "update_from_main.sh" in content


def test_runner_is_checked_before_and_after_safe_update() -> None:
    content = text()
    assert content.count("if ! ensure_actions_runner; then") == 2
    first = content.index("if ! ensure_actions_runner; then")
    update = content.index("update_from_main.sh\" 2>&1")
    second = content.rindex("if ! ensure_actions_runner; then")
    assert first < update < second


def test_watchdog_does_not_touch_trading_flags_or_secrets() -> None:
    content = text()
    assert "EXCHANGE_LIVE_TRADING_ENABLED=" not in content
    assert "TESTNET_EXECUTION_ENABLED=" not in content
    assert "EXECUTION_KILL_SWITCH=" not in content
    assert "GITHUB_RUNNER_TOKEN" not in content
    assert "GH_TOKEN" not in content
