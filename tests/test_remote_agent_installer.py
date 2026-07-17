from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "deploy" / "vps" / "install_remote_agent.sh"
UPDATER = ROOT / "deploy" / "vps" / "update_from_main.sh"


def test_remote_agent_scripts_have_valid_bash_syntax() -> None:
    subprocess.run(["bash", "-n", str(INSTALLER)], check=True)
    subprocess.run(["bash", "-n", str(UPDATER)], check=True)


def test_remote_agent_does_not_depend_on_root_ssh_home() -> None:
    installer = INSTALLER.read_text(encoding="utf-8")
    updater = UPDATER.read_text(encoding="utf-8")

    assert "ProtectHome=true" in installer
    assert "Environment=FETCH_REMOTE=${agent_fetch_url}" in installer
    assert "GIT_CONFIG_COUNT" not in installer
    assert "https://github.com/${origin_url#git@github.com:}" in installer
    assert "SHARIPOVAI_AGENT_FETCH_URL" in installer

    assert 'FETCH_REMOTE="${FETCH_REMOTE:-origin}"' in updater
    assert 'git -C "${APP_DIR}" fetch --no-tags "${FETCH_REMOTE}" "${BRANCH}"' in updater
    assert 'target_sha="$(git -C "${APP_DIR}" rev-parse FETCH_HEAD)"' in updater
    assert 'git -C "${APP_DIR}" show "${target_sha}:deploy/vps/export_backup.sh"' in updater


def test_remote_agent_fetch_url_is_fail_closed() -> None:
    installer = INSTALLER.read_text(encoding="utf-8")
    updater = UPDATER.read_text(encoding="utf-8")

    assert "agent fetch URL must be an HTTPS GitHub repository URL" in installer
    assert "set SHARIPOVAI_AGENT_FETCH_URL" in installer
    assert "systemctl reset-failed sharipovai-agent.service" in installer
    assert "FETCH_REMOTE must be a plain HTTPS GitHub repository URL" in updater
    assert "FETCH_REMOTE contains unsafe characters" in updater
