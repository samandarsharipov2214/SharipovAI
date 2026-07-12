from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"

LINUX_WORKFLOWS = (
    "ci.yml",
    "tests.yml",
    "project-guardrails.yml",
    "full-stabilization.yml",
    "stabilization-dashboard.yml",
    "production-smoke.yml",
    "web2.yml",
    "sync-bybit-skill.yml",
)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_automatic_workflows_do_not_use_github_hosted_runners() -> None:
    for path in WORKFLOWS.glob("*.yml"):
        text = _read(path)
        assert "ubuntu-latest" not in text, path
        assert "windows-latest" not in text, path


def test_linux_workflows_require_enabled_self_hosted_runner() -> None:
    for name in LINUX_WORKFLOWS:
        text = _read(WORKFLOWS / name)
        assert "SHARIPOVAI_SELF_HOSTED_CI" in text, name
        assert "runs-on: [self-hosted, linux, x64, sharipovai-ci]" in text, name


def test_windows_workflow_requires_enabled_self_hosted_pc_runner() -> None:
    text = _read(WORKFLOWS / "windows-agent-package.yml")
    assert "SHARIPOVAI_WINDOWS_SELF_HOSTED_CI" in text
    assert "runs-on: [self-hosted, Windows, X64, sharipovai-windows-ci]" in text


def test_full_suite_is_not_launched_for_every_pull_request() -> None:
    text = _read(WORKFLOWS / "full-stabilization.yml")
    trigger_section = text.split("permissions:", 1)[0]
    assert "pull_request:" not in trigger_section
    assert "push:" not in trigger_section
    assert "workflow_dispatch:" in trigger_section
    assert "schedule:" in trigger_section


def test_expensive_or_mutating_workflows_are_rate_limited() -> None:
    production = _read(WORKFLOWS / "production-smoke.yml")
    bybit_sync = _read(WORKFLOWS / "sync-bybit-skill.yml")
    assert "17 * * * *" in production
    assert "17,47 * * * *" not in production
    assert "pull_request:" not in bybit_sync.split("permissions:", 1)[0]
    assert "push:" not in bybit_sync.split("permissions:", 1)[0]
    assert "workflow_dispatch:" in bybit_sync


def test_runner_installers_never_add_runner_user_to_docker_group() -> None:
    linux_installer = _read(ROOT / "deploy" / "vps" / "install_github_actions_runner.sh")
    windows_installer = _read(ROOT / "scripts" / "windows" / "install_github_actions_runner.ps1")
    assert "usermod -aG docker" not in linux_installer
    assert "docker.sock" not in linux_installer
    assert "SHARIPOVAI_SELF_HOSTED_CI" in linux_installer
    assert "SHARIPOVAI_WINDOWS_SELF_HOSTED_CI" in windows_installer


def test_vps_bootstrap_uses_device_login_and_verifies_real_ci() -> None:
    bootstrap = _read(ROOT / "deploy" / "vps" / "bootstrap_github_actions_runner.sh")
    assert "gh auth login" in bootstrap
    assert "--web" in bootstrap
    assert "install_github_actions_runner.sh" in bootstrap
    assert "systemctl is-active" in bootstrap
    assert "gh workflow run ci.yml" in bootstrap
    assert "gh run watch" in bootstrap
    assert "SHARIPOVAI_SELF_HOSTED_CI" in bootstrap
    assert "usermod -aG docker" not in bootstrap
    assert "docker.sock" not in bootstrap
