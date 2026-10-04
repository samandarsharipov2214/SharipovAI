"""Exercise host wrappers with disposable commands, never systemd or Docker."""
import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def host(tmp_path):
    commands = tmp_path / "bin"
    commands.mkdir()
    log = tmp_path / "calls.log"
    program = '''#!/usr/bin/env python3
import json, os, pathlib, sys
name = pathlib.Path(sys.argv[0]).name
args = sys.argv[1:]
source = sys.stdin.read() if (name == 'docker' and '-i' in args) or name == 'cmp' else ''
with open(os.environ['CALL_LOG'], 'a') as out:
    out.write(json.dumps({'name': name, 'args': args, 'source': source}) + '\\n')
if name == 'git':
    if args[0] == 'rev-parse':
        print('a' * 40)
    elif args[0] == 'status':
        print(os.environ.get('DIRTY_STATUS', ''), end='')
    elif args[0] == 'show':
        print('reviewed unit')
if name == 'docker':
    if 'paper_forecast_readiness' in ' '.join(args):
        print(json.dumps({'ready': False, 'request_continuation': False,
                          'error': 'canonical_holdout_registry_unavailable'}))
        sys.exit(int(os.environ.get('CHECK_STATUS', '0')))
    if 'register(db' in source and os.environ.get('FAIL_STAGE') == 'register':
        sys.exit(7)
    if "ledger.set_status(identity,'verified'" in source and os.environ.get('FAIL_STAGE') == 'verify':
        sys.exit(8)
if name == 'install' and os.environ.get('FAIL_STAGE') == 'install':
    sys.exit(9)
if name == 'cmp' and os.environ.get('FAIL_STAGE') == 'installed_content':
    sys.exit(12)
if name == 'systemctl' and 'enable' in args and os.environ.get('FAIL_STAGE') == 'enable':
    sys.exit(10)
'''
    for name in ("docker", "git", "systemctl", "install", "cmp"):
        path = commands / name
        path.write_text(program)
        path.chmod(0o755)
    env = os.environ | {"PATH": str(commands) + os.pathsep + os.environ["PATH"],
                        "CALL_LOG": str(log), "APP_DIR": str(ROOT),
                        "MODEL_READINESS_LOCK_FILE": str(tmp_path / "readiness.lock")}
    return env, log


def calls(log):
    import json
    return [json.loads(line) for line in log.read_text().splitlines()]


def test_checker_error_json_and_nonzero_exit_are_preserved(host):
    env, log = host
    result = subprocess.run(["bash", str(ROOT / "deploy/vps/model_readiness_check.sh")],
                            env=env | {"CHECK_STATUS": "11"}, capture_output=True, text=True)
    assert result.returncode == 11
    assert "canonical_holdout_registry_unavailable" in result.stdout
    assert not any(c["name"] == "systemctl" for c in calls(log))


@pytest.mark.parametrize("stage,status", [("register", 7), ("install", 9), ("enable", 10), ("verify", 8), ("installed_content", 12)])
def test_partial_install_records_failure_and_preserves_exit(host, stage, status):
    env, log = host
    result = subprocess.run(["bash", str(ROOT / "deploy/vps/install_model_readiness.sh")],
                            env=env | {"FAIL_STAGE": stage}, capture_output=True, text=True)
    assert result.returncode == status, result.stderr
    entries = calls(log)
    assert any("ledger.create_change" in entry["source"] for entry in entries)
    assert "ledger.set_status(identity, 'failed'" in entries[-1]["source"]
    assert entries[-1]["args"][-2] == str(status)


def test_initial_check_uses_wrapper_lock_before_enabling_timer(host):
    env, log = host
    result = subprocess.run(["bash", str(ROOT / "deploy/vps/install_model_readiness.sh")],
                            env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    entries = calls(log)
    checks = [i for i, c in enumerate(entries) if "scripts.paper_forecast_readiness" in c["args"]]
    enable = next(i for i, c in enumerate(entries) if c["name"] == "systemctl" and "enable" in c["args"])
    assert len(checks) == 1 and checks[0] < enable
    assert Path(env["MODEL_READINESS_LOCK_FILE"]).exists()
    assert "ledger.set_status(identity,'verified'" in entries[-1]["source"]


@pytest.mark.parametrize("dirty", [" M deploy/vps/model_readiness_check.sh", "M  deploy/vps/systemd/sharipovai-model-readiness.service", "?? deploy/vps/unreviewed.sh"])
def test_dirty_checkout_refused_before_any_production_mutation(host, dirty):
    env, log = host
    result = subprocess.run(["bash", str(ROOT / "deploy/vps/install_model_readiness.sh")],
                            env=env | {"DIRTY_STATUS": dirty}, capture_output=True, text=True)
    assert result.returncode != 0 and "clean committed checkout" in result.stderr
    assert all(entry["name"] == "git" for entry in calls(log))
