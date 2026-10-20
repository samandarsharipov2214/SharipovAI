"""Exercise host wrappers with disposable commands, never systemd or Docker."""
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def host(tmp_path):
    commands = tmp_path / "bin"
    commands.mkdir()
    log = tmp_path / "calls.log"
    program = '''#!PYTHON_EXECUTABLE
import json, os, pathlib, sys
name = pathlib.Path(sys.argv[0]).name
args = sys.argv[1:]
if name == 'python3':
    if 'from tools.astra_supervisor import resource_state' in ' '.join(args):
        sys.exit(int(os.environ.get('GUARD_ERROR', '0')) or (75 if os.environ.get('RESOURCE_BUSY') == '1' else 0))
    os.execv(sys.executable, [sys.executable, *args])
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
        if os.environ.get('COOLDOWN') == '1':
            print(json.dumps({'ready': False, 'reasons': ['six_hour_cooldown']})); sys.exit(0)
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
'''.replace('PYTHON_EXECUTABLE', sys.executable)
    for name in ("docker", "git", "systemctl", "install", "cmp", "python3"):
        path = commands / name
        path.write_text(program)
        path.chmod(0o755)
    export_lock = tmp_path / 'export.lock'
    export_lock.touch()
    env = os.environ | {"PATH": str(commands) + os.pathsep + os.environ["PATH"],
                        "CALL_LOG": str(log), "APP_DIR": str(ROOT),
                        "ASTRA_EXPORT_LOCK_FILE": str(export_lock),
                        "ASTRA_DEPLOY_LOCK_FILE": str(tmp_path / 'deploy.lock'),
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


def test_busy_resources_defer_without_starting_metadata_scan(host):
    env, log = host
    result = subprocess.run(["bash", str(ROOT / "deploy/vps/model_readiness_check.sh")],
                            env=env | {"RESOURCE_BUSY": "1"}, capture_output=True, text=True)
    assert result.returncode == 75
    assert "DEFERRED: resource guard" in result.stdout
    assert not log.exists() or not any(c["name"] == "docker" for c in calls(log))


@pytest.mark.parametrize("reason,status", [("RESOURCE_BUSY", "75"), ("COOLDOWN", "76")])
def test_installer_accepts_deferral_and_records_no_fabricated_check(host, reason, status):
    import json
    from types import ModuleType
    env, log = host
    result = subprocess.run(["bash", str(ROOT / "deploy/vps/install_model_readiness.sh")],
                            env=env | {reason: "1"}, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    entries = calls(log)
    if reason == "RESOURCE_BUSY":
        assert not any("scripts.paper_forecast_readiness" in c["args"] for c in entries)
    assert any(c["name"] == "systemctl" and "enable" in c["args"] for c in entries)
    final = next(c for c in entries if "initial_check_status" in c["source"])
    # Execute the actual embedded finalizer against an unscanned durable state.
    # Its previous implementation raised KeyError('last_result') here.
    source = final["source"]
    harness = """
import sys,types,json
records=[]
class DB:
 def get_json(self,*args): return {'value':{'trigger_status':'not_requested','last_result':{'ready':False,'old':True}}}
class Ledger:
 def __init__(self,*args): pass
 def set_status(self,*args,**kwargs): records.append(kwargs)
m=types.ModuleType('storage');m.ProjectDatabase=DB;m.ProjectChangeLedger=Ledger
sys.modules['storage']=m
sys.argv=['-', 'a'*40, STATUS]
exec(SOURCE)
assert records[-1]['verification']['initial_check_status']=='DEFERRED'
assert records[-1]['verification']['canonical_metadata_check'] is None
assert records[-1]['verification']['continuation_requests']==0
""".replace("SOURCE", repr(source)).replace("STATUS", repr(status))
    check = subprocess.run([sys.executable, "-c", harness], capture_output=True, text=True)
    assert check.returncode == 0, check.stderr


def test_readiness_retries_only_explicit_deferrals_with_bounded_runtime():
    service = (ROOT / "deploy/vps/systemd/sharipovai-model-readiness.service").read_text()
    assert "Type=exec" in service and "RuntimeMaxSec=180" in service
    assert "RestartForceExitStatus=75" in service and "SuccessExitStatus=75" in service
    assert "RestartSec=10min" in service
    assert "StartLimitBurst=10" in service and "StartLimitIntervalSec=2h" in service
    assert "Restart=always" not in service and "Restart=on-failure" not in service


def test_guard_exception_is_not_a_resource_deferral(host):
    env, log = host
    result = subprocess.run(["bash", str(ROOT / "deploy/vps/model_readiness_check.sh")],
                            env=env | {"GUARD_ERROR": "1"}, capture_output=True, text=True)
    assert result.returncode == 1
    assert "DEFERRED" not in result.stdout
    assert not log.exists()


def test_cooldown_installer_does_not_claim_old_result_as_new_scan(host):
    env, log = host
    result = subprocess.run(["bash", str(ROOT / "deploy/vps/install_model_readiness.sh")],
                            env=env | {"COOLDOWN": "1"}, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    final = next(c for c in calls(log) if "initial_check_status" in c["source"])
    assert final["args"][-1] == "76"
    assert "if int(sys.argv[2]) == 0 else None" in final["source"]


def test_retry_window_outlasts_supported_backup_timeout():
    import re
    service = (ROOT / "deploy/vps/systemd/sharipovai-model-readiness.service").read_text()
    burst = int(re.search(r"StartLimitBurst=(\d+)", service)[1])
    interval = int(re.search(r"RestartSec=(\d+)min", service)[1])
    assert 75 < (burst - 1) * interval < 120
    assert "SuccessExitStatus=75 76" in service
    assert "RestartForceExitStatus=75\n" in service
