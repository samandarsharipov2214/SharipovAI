from pathlib import Path


INSTALLER = Path("deploy/vps/install_self_healing_agent.sh")


def test_installer_preserves_compatible_transactional_runtime() -> None:
    source = INSTALLER.read_text(encoding="utf-8")

    assert "existing_runtime_is_compatible()" in source
    assert "docker inspect sharipovai >/dev/null 2>&1" in source
    assert '(eq .Destination "/workspace") (not .RW)' in source
    assert "refusing replacement" in source
    assert "--force-recreate" not in source

    compatibility_check = source.index("existing_runtime_is_compatible ||")
    initial_install = source.index("up -d sharipovai caddy")
    assert compatibility_check < initial_install


def test_installer_still_creates_runtime_only_for_initial_install() -> None:
    source = INSTALLER.read_text(encoding="utf-8")

    existence_gate = source.index("if docker inspect sharipovai")
    initial_install = source.index("up -d sharipovai caddy")
    assert existence_gate < initial_install
    assert "systemctl enable --now sharipovai-self-healing.timer" in source
    assert "systemctl start sharipovai-self-healing.service" in source
