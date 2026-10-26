"""Backup observer failures cannot corrupt work or conceal service failures."""
import os
import fcntl
import json
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DEPLOY = ROOT / "deploy/vps"


@pytest.mark.parametrize("failure,expected", [(False, 0), (True, 1)])
def test_closed_ssh_output_does_not_abort_work_or_change_failure_code(tmp_path, failure, expected):
    source = (DEPLOY / "export_backup.sh").read_text()
    prefix = source.split('if ! [[ "$KEEP"', 1)[0]
    marker = tmp_path / "finished"
    script = prefix + ('fail "snapshot failed"\n' if failure else 'log "snapshot complete"\n')
    script += 'printf finished > "$MARKER"\n'
    read_fd, write_fd = os.pipe()
    os.close(read_fd)
    try:
        result = subprocess.run(["bash", "-c", script], stdout=write_fd, stderr=write_fd,
                                env=os.environ | {"MARKER": str(marker)}, timeout=5)
    finally:
        os.close(write_fd)
    assert result.returncode == expected
    assert marker.exists() is not failure


@pytest.mark.parametrize("status,failed,reason", [
    ('{bad json', False, 'status is invalid'),
    ('{"schema":1,"outcome":"VERIFIED","exit_code":75}', False, 'status is invalid'),
    ('{"schema":1,"outcome":"SKIPPED_ACTIVE_DEPLOYMENT","exit_code":0}', False, 'status is invalid'),
    ('{"schema":1,"outcome":"SKIPPED_ACTIVE_EXPORT","exit_code":75}', True, 'service is failed'),
    ('{"schema":1,"outcome":"SKIPPED_ACTIVE_DEPLOYMENT","exit_code":75}', True, 'service is failed'),
])
def test_invalid_receipt_or_current_service_failure_cannot_be_masked(tmp_path, status, failed, reason):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    systemctl = bin_dir / "systemctl"
    systemctl.write_text('#!/bin/sh\nif [ "$1" = is-failed ]; then exit ' + ('0' if failed else '1') + '; fi\nexit 0\n')
    systemctl.chmod(0o755)
    receipt = tmp_path / "status.json"
    receipt.write_text(status)
    result = subprocess.run(["bash", str(DEPLOY / "verify_backup_timer.sh")], capture_output=True,
                            text=True, timeout=5, env=os.environ | {
                                "PATH": str(bin_dir) + os.pathsep + os.environ["PATH"],
                                "APP_DIR": str(tmp_path), "SHARIPOVAI_BACKUP_TIMER_STATUS_FILE": str(receipt)})
    assert result.returncode != 0
    assert reason in result.stderr


@pytest.mark.parametrize("code,outcome", [(0, "VERIFIED"), (75, "SKIPPED_ACTIVE_EXPORT"), (1, "FAILED")])
def test_timer_records_export_result_without_requiring_tracked_executable_bit(tmp_path, code, outcome):
    import json
    app = tmp_path / "app"
    (app / "deploy/vps").mkdir(parents=True)
    exporter = app / "deploy/vps/export_backup.sh"
    exporter.write_text(f'exit {code}\n')
    exporter.chmod(0o644)
    state = tmp_path / "state"
    result = subprocess.run(["bash", str(DEPLOY / "backup_timer_run.sh")], capture_output=True,
                            timeout=5, env=os.environ | {"APP_DIR": str(app),
                                "LOCK_FILE": str(tmp_path / "deploy.lock"),
                                "SHARIPOVAI_BACKUP_TIMER_STATE_DIR": str(state)})
    assert result.returncode == (1 if code == 1 else 0)
    receipt = json.loads((state / "last_timer_run.json").read_text())
    assert receipt["outcome"] == outcome and receipt["exit_code"] == code


def test_scheduled_backup_skips_active_deployment_without_claiming_verified(tmp_path):
    app = tmp_path / "app"
    (app / "deploy/vps").mkdir(parents=True)
    marker = tmp_path / "exported"
    (app / "deploy/vps/export_backup.sh").write_text('touch "$EXPORT_MARKER"\n')
    state = tmp_path / "state"
    lock_path = tmp_path / "deploy.lock"
    with lock_path.open("w") as owner:
        fcntl.flock(owner, fcntl.LOCK_EX | fcntl.LOCK_NB)
        result = subprocess.run(["bash", str(DEPLOY / "backup_timer_run.sh")], capture_output=True,
            timeout=5, env=os.environ | {"APP_DIR": str(app), "LOCK_FILE": str(lock_path),
            "EXPORT_MARKER": str(marker), "SHARIPOVAI_BACKUP_TIMER_STATE_DIR": str(state)})
    assert result.returncode == 0 and not marker.exists()
    receipt = json.loads((state / "last_timer_run.json").read_text())
    assert receipt["outcome"] == "SKIPPED_ACTIVE_DEPLOYMENT" and receipt["exit_code"] == 75


def test_scheduled_export_holds_shared_deployment_lock_until_it_finishes(tmp_path):
    app = tmp_path / "app"
    (app / "deploy/vps").mkdir(parents=True)
    # The exporter checks that an updater cannot acquire its exclusive lock.
    (app / "deploy/vps/export_backup.sh").write_text('flock -xn "$LOCK_FILE" true && exit 1\nexit 0\n')
    lock_path = tmp_path / "deploy.lock"
    result = subprocess.run(["bash", str(DEPLOY / "backup_timer_run.sh")], capture_output=True,
        timeout=5, env=os.environ | {"APP_DIR": str(app), "LOCK_FILE": str(lock_path),
        "SHARIPOVAI_BACKUP_TIMER_STATE_DIR": str(tmp_path / "state")})
    assert result.returncode == 0
    with lock_path.open("r") as owner:
        fcntl.flock(owner, fcntl.LOCK_EX | fcntl.LOCK_NB)


@pytest.mark.parametrize('allow,expected', [('0',1),('1',0)])
@pytest.mark.parametrize('outcome', [None, 'SKIPPED_ACTIVE_DEPLOYMENT'])
def test_new_timer_can_reuse_verified_deployment_backup_without_false_trigger(tmp_path,allow,expected,outcome):
    import hashlib
    backup=tmp_path/'deploy/vps/backups'; backup.mkdir(parents=True)
    archive=backup/'snapshot.tar.gz'; archive.write_bytes(b'verified-test-archive')
    (backup/'snapshot.tar.gz.sha256').write_text(hashlib.sha256(archive.read_bytes()).hexdigest()+'  snapshot.tar.gz\n')
    (backup/'latest.tar.gz').symlink_to(archive.name)
    bin_dir=tmp_path/'bin'; bin_dir.mkdir()
    cmd=bin_dir/'systemctl'
    cmd.write_text('''#!/bin/sh
if [ "$1" = is-failed ]; then exit 1; fi
case "$*" in *NextElapseUSecRealtime*) printf 'future-calendar-run\\n';; esac
exit 0
''')
    cmd.chmod(0o755)
    receipt = tmp_path / 'status.json'
    if outcome:
        receipt.write_text(json.dumps({'schema':1,'outcome':outcome,'exit_code':75}))
    result=subprocess.run(['bash',str(DEPLOY/'verify_backup_timer.sh')],capture_output=True,timeout=5,
        env=os.environ|{'APP_DIR':str(tmp_path),'PATH':str(bin_dir)+os.pathsep+os.environ['PATH'],
                        'BACKUP_ALLOW_UNTRIGGERED_TIMER':allow,
                        'SHARIPOVAI_BACKUP_TIMER_STATUS_FILE':str(receipt)})
    assert result.returncode==expected, result.stderr
