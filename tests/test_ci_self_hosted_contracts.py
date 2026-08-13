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


def test_legacy_ai_autofix_is_evidence_only_and_cannot_mutate_repository() -> None:
    workflow = _read(WORKFLOWS / "ai-autofix.yml")

    assert "contents: read" in workflow
    for forbidden in (
        "contents: write",
        "pull-requests: write",
        "issues: write",
        "OPENAI_API_KEY",
        "OPENAI_MODEL",
        "AI_AUTOFIX_ATTEMPTS",
        "git add .",
        "git commit",
        "git push",
        "issue_comment:",
    ):
        assert forbidden not in workflow
    assert "Run evidence-only pytest" in workflow
    assert "python scripts/ai_autofix.py" in workflow
    assert "persist-credentials: false" in workflow


def test_production_smoke_requires_canonical_configured_public_endpoint() -> None:
    workflow = _read(WORKFLOWS / "production-smoke.yml")

    assert "SHARIPOVAI_PRODUCTION_BASE_URL" in workflow
    assert "sharipovai-bot.onrender.com" not in workflow
    assert "--public-liveness-only" in workflow
    assert "repository variable is required" in workflow


def test_web2_workflow_does_not_reference_missing_lockfile() -> None:
    workflow = _read(WORKFLOWS / "web2.yml")

    assert "package-lock.json" not in workflow
    assert "cache: npm" not in workflow
    assert "npm install --ignore-scripts --no-audit --no-fund" in workflow
    assert 'listener.bind(("127.0.0.1", 0))' in workflow
    assert '"http://127.0.0.1:${PORT}/"' in workflow
    assert "cat /tmp/sharipoai-web2.log >&2 || true" in workflow


def test_runner_installers_never_add_runner_user_to_docker_group() -> None:
    linux_installer = _read(ROOT / "deploy" / "vps" / "install_github_actions_runner.sh")
    windows_installer = _read(ROOT / "scripts" / "windows" / "install_github_actions_runner.ps1")
    assert "usermod -aG docker" not in linux_installer
    assert "docker.sock" not in linux_installer
    assert "SHARIPOVAI_SELF_HOSTED_CI" in linux_installer
    assert "SHARIPOVAI_WINDOWS_SELF_HOSTED_CI" in windows_installer


def test_linux_runner_service_commands_execute_from_runner_root() -> None:
    installer = _read(ROOT / "deploy" / "vps" / "install_github_actions_runner.sh")
    assert 'run_svc() { (cd "${RUNNER_HOME}" && ./svc.sh "$@"); }' in installer
    assert 'run_svc install "${RUNNER_USER}"' in installer
    assert "run_svc start" in installer
    assert '"${RUNNER_HOME}/svc.sh" install' not in installer
    assert '"${RUNNER_HOME}/svc.sh" start' not in installer


def test_vps_bootstrap_uses_device_login_and_verifies_real_ci() -> None:
    bootstrap = _read(ROOT / "deploy" / "vps" / "bootstrap_github_actions_runner.sh")
    assert "gh auth login" in bootstrap
    assert "--web" in bootstrap
    assert "--git-protocol https" in bootstrap
    assert "install_github_actions_runner.sh" in bootstrap
    assert "systemctl is-active" in bootstrap
    assert "actions/variables/SHARIPOVAI_SELF_HOSTED_CI" in bootstrap
    assert "actions/workflows/ci.yml/dispatches" in bootstrap
    assert "actions/runs/${run_id}" in bootstrap
    assert "BOOTSTRAP_SUCCEEDED" in bootstrap
    assert "gh variable get" not in bootstrap
    assert "gh workflow run" not in bootstrap
    assert "gh run watch" not in bootstrap
    assert "usermod -aG docker" not in bootstrap
    assert "docker.sock" not in bootstrap
