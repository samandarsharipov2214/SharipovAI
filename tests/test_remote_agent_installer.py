from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "deploy" / "vps" / "install_remote_agent.sh"


def test_remote_agent_installer_has_valid_bash_syntax() -> None:
    subprocess.run(["bash", "-n", str(INSTALLER)], check=True)


def test_remote_agent_does_not_depend_on_root_ssh_home() -> None:
    source = INSTALLER.read_text(encoding="utf-8")

    assert "ProtectHome=true" in source
    assert "GIT_CONFIG_COUNT=1" in source
    assert "GIT_CONFIG_KEY_0=remote.origin.url" in source
    assert "GIT_CONFIG_VALUE_0=${agent_fetch_url}" in source
    assert "https://github.com/${origin_url#git@github.com:}" in source
    assert "SHARIPOVAI_AGENT_FETCH_URL" in source


def test_remote_agent_fetch_url_is_fail_closed() -> None:
    source = INSTALLER.read_text(encoding="utf-8")

    assert "agent fetch URL must be an HTTPS GitHub repository URL" in source
    assert "set SHARIPOVAI_AGENT_FETCH_URL" in source
    assert "systemctl reset-failed sharipovai-agent.service" in source
