"""Exercise the actual immutable shell-embedded probe with a monotonic clock."""
from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = [ROOT / "deploy/vps" / name for name in ("update_from_main.sh", "phase11_rollback.sh")]


def _probe_source(path):
    return path.read_text().split("<<'HEALTH_PY'\n", 1)[1].split("\nHEALTH_PY", 1)[0]


def _harness(path, *, docker_ready=216, http_ready=216, hang=None, docker_state="running", http_code="200"):
    namespace = {"__name__": "health_contract_test"}
    exec(compile(_probe_source(path), str(path), "exec"), namespace)
    clock = SimpleNamespace(now=0.0)
    calls = []

    def sleep(seconds):
        assert 0 < seconds <= 30
        clock.now += seconds

    def run(command, **kwargs):
        budget = kwargs["timeout"]
        assert 0 < budget <= 5
        calls.append((clock.now, command[0], budget))
        if command[0] == hang:
            clock.now += budget
            raise subprocess.TimeoutExpired(command, budget)
        if command[0] == "docker":
            status = "healthy" if clock.now >= docker_ready else "starting"
            return SimpleNamespace(returncode=0, stdout=f"{docker_state} {status} 0 0 false\n")
        assert command[0] == "curl"
        return SimpleNamespace(returncode=0 if clock.now >= http_ready else 22, stdout=http_code)

    namespace["time"] = SimpleNamespace(monotonic=lambda: clock.now, sleep=sleep)
    namespace["subprocess"] = SimpleNamespace(run=run, PIPE=subprocess.PIPE,
        DEVNULL=subprocess.DEVNULL, TimeoutExpired=subprocess.TimeoutExpired)
    return namespace["check_health"], clock, calls


@pytest.mark.parametrize("path", SCRIPTS)
@pytest.mark.parametrize("ready,delay", [(216, 2), (359, 1)])
def test_known_good_and_late_startup_are_accepted(path, ready, delay):
    check, clock, calls = _harness(path, docker_ready=ready, http_ready=ready)
    assert check("http://localhost/health", 360, delay)
    assert clock.now == ready
    assert calls[-1][1] == "curl"


@pytest.mark.parametrize("path", SCRIPTS)
@pytest.mark.parametrize("docker_ready,http_ready", [(400, 0), (0, 400)])
def test_both_docker_and_http_are_required(path, docker_ready, http_ready, capsys):
    check, clock, calls = _harness(path, docker_ready=docker_ready, http_ready=http_ready)
    assert not check("http://localhost/health", 360, 2)
    assert clock.now == 360
    if docker_ready == 400:
        assert all(call[1] == "docker" for call in calls)
    error = capsys.readouterr().err
    assert "HEALTH_TIMEOUT" in error
    assert "restarts=0 exit=0 oom=false" in error


@pytest.mark.parametrize("path", SCRIPTS)
@pytest.mark.parametrize("hang", ["docker", "curl"])
def test_hung_probes_consume_remaining_deadline_without_overrun(path, hang, capsys):
    check, clock, calls = _harness(path, docker_ready=0, http_ready=0, hang=hang)
    assert not check("http://private-placeholder/health", 17, 2)
    assert clock.now == 17
    assert all(at + budget <= 17 for at, _, budget in calls)
    error = capsys.readouterr().err
    assert "TimeoutExpired" in error
    assert "private-placeholder" not in error


@pytest.mark.parametrize("path", SCRIPTS)
def test_restart_or_exited_state_cannot_pass_with_old_healthy_field(path):
    check, clock, calls = _harness(path, docker_ready=0, http_ready=0, docker_state="restarting")
    assert not check("http://localhost/health", 3, 2)
    assert clock.now == 3
    assert all(call[1] == "docker" for call in calls)


@pytest.mark.parametrize("code", ["", "302", "401", "500"])
def test_redirect_or_non_200_http_cannot_count_as_ready(code):
    check, clock, _ = _harness(SCRIPTS[0], docker_ready=0, http_ready=0, http_code=code)
    assert not check("http://localhost/health", 3, 2)
    assert clock.now == 3


@pytest.mark.parametrize("path", SCRIPTS)
def test_each_candidate_or_rollback_receives_full_new_deadline(path):
    check, clock, _ = _harness(path, docker_ready=400, http_ready=400)
    assert not check("http://localhost/health", 360, 2)
    assert check("http://localhost/health", 360, 2)
    assert clock.now == 400


@pytest.mark.parametrize("timeout,delay", [(0, 2), (float("inf"), 2), (3601, 2),
    (float("nan"), 2), (360, 0), (360, -1), (360, float("nan")), (360, 31)])
def test_invalid_configuration_never_probes_or_waits(timeout, delay):
    check, clock, calls = _harness(SCRIPTS[0])
    with pytest.raises(ValueError):
        check("http://localhost/health", timeout, delay)
    assert clock.now == 0
    assert not calls


def test_candidate_and_rollback_have_identical_immutable_probe_and_safe_defaults():
    assert _probe_source(SCRIPTS[0]) == _probe_source(SCRIPTS[1])
    for path in SCRIPTS:
        source = path.read_text()
        assert 'HEALTH_TIMEOUT_SECONDS:-360}' in source
        assert 'http://127.0.0.1:8000/health' in source
        assert 'HEALTH_ATTEMPTS=' not in source
        function = source[source.index('health_check()'):source.index('\nset_build_provenance()')]
        assert 'time.monotonic()' in function
        assert 'time.time()' not in function
        assert 'docker logs' not in function
        # The function is parsed before a checkout can replace its script file.
        assert source.index('health_check()') < source.index('reset --hard')
