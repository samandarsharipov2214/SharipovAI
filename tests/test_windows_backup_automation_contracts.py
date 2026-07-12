from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8-sig")


def test_sync_supports_dedicated_identity_and_batch_mode() -> None:
    script = read("scripts/windows/sync_vps_backup.ps1")
    assert "[string]$IdentityFile" in script
    assert '"BatchMode=yes"' in script
    assert '"IdentitiesOnly=yes"' in script
    assert "@sshOptions" in script
    assert '"/opt/sharipovai-repo"' in script


def test_scheduled_sync_preserves_app_dir_and_identity() -> None:
    script = read("scripts/windows/install_vps_backup_sync.ps1")
    assert "[string]$VpsAppDir" in script
    assert "[string]$IdentityFile" in script
    assert '-VpsAppDir `"$VpsAppDir`"' in script
    assert '-IdentityFile `"$IdentityFile`"' in script
    assert "-MultipleInstances IgnoreNew" in script


def test_one_command_setup_creates_and_verifies_dedicated_key() -> None:
    script = read("scripts/windows/configure_vps_backup_automation.ps1")
    assert "sharipovai_backup_ed25519" in script
    assert "ssh-keygen.exe" in script
    assert "scp.exe" in script
    assert "authorized_keys" in script
    assert "/tmp/sharipovai_backup_ed25519.pub" in script
    assert "grep -Fqx -f" in script
    assert "publicKeyRaw" in script
    assert "(?:\\s+.*)?$" in script
    assert '$publicKeyBase = "$($Matches[1]) $($Matches[2])"' in script
    assert "function Invoke-NativeCapture" in script
    assert "function Invoke-NativeInteractive" in script
    assert '$ErrorActionPreference = "SilentlyContinue"' in script
    assert '$ErrorActionPreference = "Continue"' in script
    assert "Invoke-NativeCapture -FilePath $ssh.Source" in script
    assert "Invoke-NativeInteractive -FilePath $scp.Source" in script
    assert "BatchMode=yes" in script
    assert "backup-key-ok" in script
    assert "install_vps_backup_sync.ps1" in script
    assert "passive backup automation is installed and verified" in script
