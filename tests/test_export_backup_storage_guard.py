from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tarfile
import time
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "deploy" / "vps" / "export_backup.sh"


def _script() -> str:
    return SCRIPT.read_text(encoding="utf-8")


def test_export_backup_script_has_valid_bash_syntax() -> None:
    subprocess.run(["bash", "-n", str(SCRIPT)], check=True)


def test_backup_fails_closed_before_staging_when_disk_headroom_is_low() -> None:
    text = _script()
    assert "SHARIPOVAI_BACKUP_MIN_FREE_DISK_GB:-20" in text
    assert "SHARIPOVAI_BACKUP_RESERVE_MIB:-512" in text
    assert "df -P -B1" in text
    assert "require_free_space 0 'initial preflight'" in text
    assert "require_free_space \"$source_bytes\" 'before staging persistent data'" in text
    assert "require_free_space 1048576 'before bounded archive creation'" in text
    assert "BudgetWriter" in text
    assert text.index("require_free_space 0 'initial preflight'") < text.index("work=$(mktemp -d")


def test_backup_only_removes_stale_staging_after_exclusive_lock() -> None:
    text = _script()
    lock = text.index("flock -n 9")
    cleanup_call = text.index("cleanup_stale_staging\n")
    assert lock < cleanup_call
    assert "-type d -name '.staging-*' -print0" in text
    assert '[[ "$stale" == "$BACKUP_DIR"/.staging-* ]]' in text
    assert 'rm -rf -- "$stale"' in text
    assert "docker system prune" not in text
    assert "docker image prune" not in text
    assert "docker volume prune" not in text


def test_backup_helper_is_bounded_identifiable_and_still_isolated() -> None:
    text = _script()
    assert "SHARIPOVAI_BACKUP_HELPER_TIMEOUT_SECONDS:-600" in text
    assert 'timeout --foreground --kill-after=10s "${HELPER_TIMEOUT_SECONDS}s"' in text
    assert '--name "$helper_name"' in text
    assert "--label 'com.sharipovai.role=backup-helper'" in text
    assert '--label "com.sharipovai.run=$run_id"' in text
    assert "--no-healthcheck" in text
    assert "--network none" in text
    assert "--read-only" in text
    assert "--security-opt no-new-privileges:true" in text
    assert "--cap-drop ALL" in text
    assert '-v "$volume_name:/source:ro"' in text


def test_helper_cleanup_requires_exact_role_and_run_labels() -> None:
    text = _script()
    assert 'helper_id=$(docker inspect --format \'{{.Id}}\' "$helper_name"' in text
    assert 'role=$(docker inspect --format \'{{index .Config.Labels "com.sharipovai.role"}}\'' in text
    assert 'helper_run=$(docker inspect --format \'{{index .Config.Labels "com.sharipovai.run"}}\'' in text
    assert "[[ \"$role\" == 'backup-helper' && \"$helper_run\" == \"$run_id\" ]]" in text
    assert 'docker rm -f "$helper_id"' in text
    assert "refusing to remove helper candidate with unexpected labels" in text


def test_hashing_is_streaming_and_host_heavy_work_is_deprioritized() -> None:
    text = _script()
    assert ".read_bytes()" not in text
    assert 'handle.read(1024 * 1024)' in text
    assert "ionice -c2 -n7 nice -n 10" in text
    assert 'run_low_priority python3 - "$work" "$archive_tmp"' in text
    assert 'run_low_priority sha256sum "$archive_tmp"' in text


def test_archive_is_published_only_after_complete_partial_file() -> None:
    text = _script()
    assert 'archive_tmp=$(mktemp "$BACKUP_DIR/.sharipovai-$stamp.tar.gz.partial-XXXXXX")' in text
    assert 'tarfile.open(fileobj=writer, mode="w|gz")' in text
    verify = 'tar -tzf "$archive_tmp" >/dev/null'
    assert verify in text
    assert "fail 'backup archive integrity verification failed or timed out'" in text
    assert text.index(verify) < text.index('archive_digest=$(run_low_priority sha256sum')
    assert 'mv "$archive_checksum_tmp" "$archive.sha256"' in text
    assert 'mv "$archive_tmp" "$archive"' in text
    assert '[[ "$candidate" == "$BACKUP_DIR"/.sharipovai-*.partial-* ]]' in text
    assert 'rm -f -- "$candidate"' in text


def _live_size_export(tmp_path: Path, scenario: str):
    """Run the exporter with isolated Docker transport and a controlled stat race."""
    mock_bin = tmp_path / "bin"
    mock_bin.mkdir()
    source = tmp_path / "volume"
    source.mkdir()
    (source / "autonomous_paper.json").write_text('{"mode":"paper"}')
    compose = tmp_path / "compose"
    compose.mkdir()
    scripts = {
        "df": "#!/bin/sh\nprintf 'Filesystem 1B-blocks Used Available Use%% Mounted\\n/mock 1 0 107374182400 0%% /\\n'\n",
        "docker": r'''#!/usr/bin/env python3
import os, shutil, sys
from pathlib import Path
a = sys.argv[1:]
if a[:2] == ['container', 'ls']:
    print('live-container')
elif a[:2] == ['inspect', '--format']:
    if a[-1] != 'live-container':
        sys.exit(1)
    for key, value in {'.Id': 'live-container', 'ai.sharipov.service': 'dashboard',
                       'ai.sharipov.runtime-mode': 'production-safe',
                       'com.docker.compose.service': 'sharipovai',
                       'State.Running': 'true', 'Mounts': 'live-volume',
                       'Config.Image': 'live-image'}.items():
        if key in a[2]:
            print(value)
            break
elif a[:2] == ['volume', 'inspect']:
    if '--format' in a:
        print(os.environ['PROBE_SOURCE'])
elif a[:2] == ['image', 'inspect']:
    pass
elif a[0] == 'run':
    Path(os.environ['HELPER_MARKER']).touch()
    dest = next(v.removesuffix(':/backup') for v in a if v.endswith(':/backup'))
    shutil.copytree(os.environ['PROBE_SOURCE'], dest, dirs_exist_ok=True)
else:
    sys.exit(97)
''',
        "du": r'''#!/usr/bin/env python3
import os, subprocess, sys, time
from pathlib import Path
source = Path(os.environ['PROBE_SOURCE'])
if sys.argv[-1] != str(source):
    os.execv(os.environ['REAL_DU'], [os.environ['REAL_DU'], *sys.argv[1:]])
trace = Path(os.environ['PROBE_TRACE'])
attempt = len(trace.read_text().splitlines()) + 1 if trace.exists() else 1
with trace.open('a') as stream:
    stream.write(f'{attempt}\n')
scenario = os.environ['PROBE_SCENARIO']
def missing(path, code=1):
    print(f"du: cannot access '{path}': No such file or directory", file=sys.stderr)
    sys.exit(code)
if scenario in ('race', 'churn', 'mixed') and (attempt == 1 or scenario == 'churn'):
    temp = source / '.autonomous_paper.json.123.456.tmp'
    temp.write_text('{}')
    entries = list(os.scandir(source))
    temp.unlink()  # Writer's legitimate enumeration-to-stat disappearance.
    for entry in entries:
        if entry.name == temp.name:
            try:
                entry.stat(follow_symlinks=False)
            except FileNotFoundError:
                if scenario == 'mixed':
                    print(f"du: cannot read directory '{source}/private': Permission denied", file=sys.stderr)
                missing(temp)
    sys.exit('test did not reproduce ENOENT')
if scenario == 'permission':
    print(f"du: cannot read directory '{source}/private': Permission denied", file=sys.stderr)
    sys.exit(1)
if scenario == 'io':
    print(f"du: cannot access '{source}/state': Input/output error", file=sys.stderr)
    sys.exit(1)
if scenario == 'arbitrary':
    print('du: unexpected error', file=sys.stderr)
    sys.exit(1)
if scenario == 'empty_error':
    sys.exit(1)
if scenario == 'timeout':
    time.sleep(30)
if scenario == 'source_missing':
    for entry in source.iterdir():
        entry.unlink()
    source.rmdir()
    missing(source)
if scenario == 'source_replaced':
    source.rename(source.with_name('old-volume'))
    source.mkdir()
    missing(source / 'temp')
if scenario == 'outside':
    missing(source.parent / 'other/temp')
if scenario == 'traversal':
    missing(str(source) + '/../other/temp')
if scenario == 'symlink':
    (source / 'escape').symlink_to(source.parent, target_is_directory=True)
    missing(source / 'escape/temp')
if scenario == 'wrong_exit':
    missing(source / 'temp', 2)
if scenario == 'root_diagnostic':
    missing(source)
if scenario == 'invalid':
    sys.stdout.buffer.write(b'invalid\t' + os.fsencode(source) + b'\0')
    sys.exit(0)
if scenario == 'negative':
    sys.stdout.buffer.write(b'-1\t' + os.fsencode(source) + b'\0')
    sys.exit(0)
if scenario in ('huge', 'zero'):
    size = b'18446744073709551616' if scenario == 'huge' else b'0'
    sys.stdout.buffer.write(size + b'\t' + os.fsencode(source) + b'\0')
    sys.exit(0)
if scenario == 'extra_output':
    sys.stdout.buffer.write(b'1\t' + os.fsencode(source) + b'\0extra')
    sys.exit(0)
if scenario == 'success_stderr':
    print('du: unexpected diagnostic', file=sys.stderr)
os.execv(os.environ['REAL_DU'], [os.environ['REAL_DU'], *sys.argv[1:]])
''',
    }
    for name, code in scripts.items():
        path = mock_bin / name
        path.write_text(code)
        path.chmod(0o755)
    backup = tmp_path / "backups"
    started = time.monotonic()
    result = subprocess.run(
        ["bash", str(SCRIPT)], text=True, capture_output=True, timeout=15,
        env=os.environ | {
            "PATH": f"{mock_bin}:{os.environ['PATH']}",
            "APP_DIR": str(ROOT), "COMPOSE_DIR": str(compose), "BACKUP_DIR": str(backup),
            "PROBE_SOURCE": str(source), "PROBE_SCENARIO": scenario,
            "PROBE_TRACE": str(tmp_path / "probe.trace"),
            "HELPER_MARKER": str(tmp_path / "helper.started"), "REAL_DU": shutil.which("du"),
            "SHARIPOVAI_BACKUP_MIN_FREE_DISK_GB": "1", "SHARIPOVAI_BACKUP_RESERVE_MIB": "0",
            "SHARIPOVAI_BACKUP_SIZE_PROBE_TIMEOUT_SECONDS": "5",
        },
    )
    attempts = len((tmp_path / "probe.trace").read_text().splitlines())
    assert not list(backup.glob(".staging-*"))
    assert not list(backup.glob("*.partial-*"))
    return result, attempts, time.monotonic() - started


@pytest.mark.parametrize(("scenario", "attempts"), [("normal", 1), ("race", 2), ("zero", 1)])
def test_live_size_probe_publishes_backup_after_valid_measurement(tmp_path, scenario, attempts):
    result, actual, _ = _live_size_export(tmp_path, scenario)
    assert result.returncode == 0, result.stderr
    assert actual == attempts
    if scenario == "race":
        assert "No such file or directory" in result.stderr
        assert "retrying size probe (1/3)" in result.stderr
    archive = next((tmp_path / "backups").glob("sharipovai-*.tar.gz"))
    assert hashlib.sha256(archive.read_bytes()).hexdigest() in Path(str(archive) + ".sha256").read_text()
    with tarfile.open(archive) as tar:
        manifest = json.load(tar.extractfile("manifest.json"))
        assert manifest["file_count"] == 1
        assert tar.extractfile("data/autonomous_paper.json").read() == b'{"mode":"paper"}'


@pytest.mark.parametrize(
    ("scenario", "attempts", "diagnostic"),
    [
        ("churn", 3, "exhausted 3"),
        ("permission", 1, "Permission denied"), ("mixed", 1, "Permission denied"),
        ("io", 1, "Input/output error"), ("arbitrary", 1, "unexpected error"),
        ("empty_error", 1, "size probe failed"), ("wrong_exit", 1, "exit=2"),
        ("timeout", 1, "timed out"), ("invalid", 1, "invalid value"),
        ("negative", 1, "invalid value"), ("extra_output", 1, "invalid value"),
        ("success_stderr", 1, "unexpected diagnostic"),
        ("source_missing", 1, "No such file"), ("source_replaced", 1, "source changed"),
        ("outside", 1, "size probe failed"), ("traversal", 1, "size probe failed"),
        ("symlink", 1, "size probe failed"), ("root_diagnostic", 1, "size probe failed"),
        ("huge", 1, "required=18446744074783293440B"),
    ],
)
def test_live_size_probe_fails_closed_before_staging(tmp_path, scenario, attempts, diagnostic):
    result, actual, elapsed = _live_size_export(tmp_path, scenario)
    assert result.returncode != 0
    assert actual == attempts
    assert diagnostic in result.stderr
    assert not (tmp_path / "helper.started").exists()
    assert not list((tmp_path / "backups").glob("*.tar.gz"))
    if scenario == "timeout":
        assert 4 <= elapsed < 12
