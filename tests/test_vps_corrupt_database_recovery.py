from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "deploy" / "vps" / "recover_corrupt_database_and_deploy.sh"


def test_recovery_script_has_valid_bash_syntax() -> None:
    subprocess.run(["bash", "-n", str(SCRIPT)], check=True)


def test_recovery_script_preserves_data_before_mutation() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    emergency_copy = source.index('cp -a "${data_mount_source}/." "${ORIGINAL_DATA}/"')
    container_rename = source.index('docker rename "${CONTAINER}" "${RENAMED_CONTAINER}"')
    volume_clear = source.index('find "${expected_mount}" -mindepth 1')

    assert emergency_copy < container_rename < volume_clear
    assert 'original-data.tar.gz.sha256' in source
    assert 'sha256sum "${RECOVERY_ROOT}/original-data.tar.gz"' in source


def test_recovery_script_validates_database_and_financial_locks() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    assert 'PRAGMA quick_check' in source
    assert 'SQLite format 3\\x00' in source
    assert 'EXCHANGE_LIVE_TRADING_ENABLED' in source
    assert 'EXECUTION_KILL_SWITCH' in source
    assert 'TESTNET_EXECUTION_ENABLED' in source
    assert 'FEATURE_BYBIT_LIVE_EXECUTION' in source


def test_recovery_script_never_deletes_corrupt_database_without_quarantine() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    assert '.corrupt-${STAMP}' in source
    assert 'no valid database backup found' in source
    assert 'emergency archive:' in source
    assert 'docker rm "${RENAMED_CONTAINER}"' in source
    assert 'health_check' in source
