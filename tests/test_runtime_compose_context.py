from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from deploy.vps.runtime_compose_context import LOCKS, runtime_context

SHA = "a" * 40
IMAGE = "sha256:" + "b" * 64
ROOT = Path(__file__).resolve().parents[1]


def runtime():
    app = {
        "Name": "/sharipovai",
        "State": {"Status": "running", "Health": {"Status": "healthy"}},
        "Image": IMAGE,
        "Config": {
            "Labels": {"ai.sharipov.service": "dashboard", "ai.sharipov.runtime-mode": "production-safe",
                       "com.docker.compose.service": "sharipovai", "com.docker.compose.project": "sharipovai-runtime-123"},
            "Env": [*(f"{k}={v}" for k, v in LOCKS.items()), f"SHARIPOVAI_BUILD_SHA={SHA}", "UNRELATED_PRIVATE_VALUE=must-not-export"],
        },
        "Mounts": [{"Type": "volume", "Name": "retained-data", "Destination": "/var/lib/sharipovai"}],
        "NetworkSettings": {"Networks": {"shared-proxy": {}}},
    }
    proxy = {"Name": "/sharipovai-caddy", "State": {"Status": "running"},
             "Config": {"Labels": {"com.docker.compose.service": "caddy"}},
             "NetworkSettings": {"Networks": {"shared-proxy": {}}}}
    image = {"Id": IMAGE, "Config": {"Labels": {"org.opencontainers.image.revision": SHA}}}
    return app, proxy, image


def test_transactional_project_preserves_external_volume_and_proxy():
    context = runtime_context(*runtime(), SHA)
    assert context["project"] == "sharipovai-runtime-123"
    assert context["override"] == {
        "volumes": {"sharipovai_data": {"external": True, "name": "retained-data"}},
        "networks": {"default": {"external": True, "name": "shared-proxy"}},
    }
    assert "must-not-export" not in json.dumps(context)


@pytest.mark.parametrize("field", ["image_id", "revision", "build_sha", "project", "volume", "network", "multiple_networks"])
def test_unproven_runtime_context_is_blocked(field):
    app, proxy, image = runtime()
    if field == "image_id": image["Id"] = "sha256:" + "c" * 64
    if field == "revision": image["Config"]["Labels"]["org.opencontainers.image.revision"] = "d" * 40
    if field == "build_sha": app["Config"]["Env"][-2] = "SHARIPOVAI_BUILD_SHA=unknown"
    if field == "project": app["Config"]["Labels"]["com.docker.compose.project"] = "../wrong"
    if field == "volume": app["Mounts"][0]["Type"] = "bind"
    if field == "network": proxy["NetworkSettings"]["Networks"] = {"other": {}}
    if field == "multiple_networks":
        app["NetworkSettings"]["Networks"]["other"] = {}
        proxy["NetworkSettings"]["Networks"]["other"] = {}
    with pytest.raises(ValueError):
        runtime_context(app, proxy, image, SHA)


@pytest.mark.parametrize("flag", list(LOCKS))
def test_every_safety_flag_is_required_and_fail_closed(flag):
    app, proxy, image = runtime()
    app["Config"]["Env"] = [v for v in app["Config"]["Env"] if not v.startswith(flag + "=")]
    with pytest.raises(ValueError, match="safety invariant"):
        runtime_context(app, proxy, image, SHA)
    app["Config"]["Env"].append(flag + "=unsafe")
    with pytest.raises(ValueError, match="safety invariant"):
        runtime_context(app, proxy, image, SHA)


@pytest.mark.parametrize("project", ["", "../vps", "-p", "vps;id", "$(id)", "vps\nother", "UPPER", "vps.other"])
def test_missing_or_unsafe_compose_project_is_blocked(project):
    app, proxy, image = runtime()
    app["Config"]["Labels"]["com.docker.compose.project"] = project
    with pytest.raises(ValueError, match="Compose project"):
        runtime_context(app, proxy, image, SHA)


@pytest.mark.parametrize("field", ["missing_app", "stopped_app", "unhealthy_app", "no_health", "missing_proxy",
                                  "stopped_proxy", "wrong_proxy_service", "missing_volume", "duplicate_volume",
                                  "wrong_destination", "unsafe_volume", "malformed_image", "missing_project",
                                  "wrong_service", "wrong_mode", "wrong_owner", "unsafe_network"])
def test_required_runtime_structure_fails_closed(field):
    app, proxy, image = runtime()
    if field == "missing_app": app = {}
    if field == "stopped_app": app["State"]["Status"] = "exited"
    if field == "unhealthy_app": app["State"]["Health"]["Status"] = "starting"
    if field == "no_health": del app["State"]["Health"]
    if field == "missing_proxy": proxy = {}
    if field == "stopped_proxy": proxy["State"]["Status"] = "exited"
    if field == "wrong_proxy_service": proxy["Config"]["Labels"]["com.docker.compose.service"] = "other"
    if field == "missing_volume": app["Mounts"] = []
    if field == "duplicate_volume": app["Mounts"] *= 2
    if field == "wrong_destination": app["Mounts"][0]["Destination"] = "/data"
    if field == "unsafe_volume": app["Mounts"][0]["Name"] = "../data"
    if field == "malformed_image": app["Image"] = image["Id"] = "sha256:short"
    if field == "missing_project": del app["Config"]["Labels"]["com.docker.compose.project"]
    if field == "wrong_service": app["Config"]["Labels"]["com.docker.compose.service"] = "other"
    if field == "wrong_mode": app["Config"]["Labels"]["ai.sharipov.runtime-mode"] = "test"
    if field == "wrong_owner": app["Config"]["Labels"]["ai.sharipov.service"] = "other"
    if field == "unsafe_network":
        app["NetworkSettings"]["Networks"] = proxy["NetworkSettings"]["Networks"] = {"../network": {}}
    with pytest.raises(ValueError):
        runtime_context(app, proxy, image, SHA)


@pytest.mark.parametrize("sha", ["", "a" * 12, "a" * 39, "a" * 41, "A" * 40])
def test_expected_revision_must_be_full_sha(sha):
    with pytest.raises(ValueError, match="full SHA"):
        runtime_context(*runtime(), sha)


def test_update_and_rollback_scope_operations_to_actual_app_project():
    for filename in ("update_from_main.sh", "phase11_rollback.sh"):
        source = (ROOT / "deploy/vps" / filename).read_text()
        assert "runtime_compose_context.py" in source
        assert "export COMPOSE_PROJECT_NAME" in source
        assert "export COMPOSE_FILE=" in source
        assert "docker compose up -d --no-deps --no-build sharipovai" in source
        assert "--remove-orphans" not in source
    source = (ROOT / "deploy/vps/update_from_main.sh").read_text()
    assert source.index('retain_running_image_for_rollback "${previous_sha}"') < source.index('reset --hard "${target_sha}"')
    assert "production checkout is not clean" in source


def _git(root, *args):
    return subprocess.check_output(["git", "-C", str(root), *args], text=True, stderr=subprocess.PIPE).strip()


def _bootstrap_fixture(tmp_path, *, mode="ok", broken_helper=False):
    """Real Git history, real target helper, fake Docker/HTTP; no daemon access."""
    remote, checkout, binaries = (tmp_path / name for name in ("remote", "checkout", "bin"))
    remote.mkdir()
    binaries.mkdir()
    _git(remote, "init", "--bare", "--initial-branch=main")
    subprocess.run(["git", "clone", str(remote), str(checkout)], check=True, capture_output=True)
    _git(checkout, "config", "user.name", "Runtime fixture")
    _git(checkout, "config", "user.email", "fixture@example.invalid")
    compose = checkout / "deploy/vps"
    compose.mkdir(parents=True)
    (checkout / ".gitignore").write_text("deploy/vps/.env.vps\n")
    (compose / ".env.vps").write_text("FIXTURE_ONLY=1\n")
    (compose / ".env.vps").chmod(0o600)
    (compose / "docker-compose.yml").write_text("services: {}\n")
    _git(checkout, "add", ".")
    _git(checkout, "commit", "-m", "Old production without helper")
    old = _git(checkout, "rev-parse", "HEAD")
    helper = ROOT / "deploy/vps/runtime_compose_context.py"
    (compose / helper.name).write_text("not valid python !!!" if broken_helper else helper.read_text())
    for filename, event in (("phase7_preflight.sh", "preflight"), ("export_backup.sh", "backup")):
        (compose / filename).write_text(f'#!/bin/bash\nprintf \'{{"action":"{event}"}}\\n\' >>"$FAKE_LOG"\n')
    _git(checkout, "add", ".")
    _git(checkout, "commit", "-m", "Target introduces trusted helper")
    target = _git(checkout, "rev-parse", "HEAD")
    _git(checkout, "push", "origin", "main")
    _git(checkout, "reset", "--hard", old)
    app, proxy, image = runtime()
    app["Config"]["Env"] = [*map(lambda p: "=".join(p), LOCKS.items()), f"SHARIPOVAI_BUILD_SHA={old}"]
    image["Config"]["Labels"]["org.opencontainers.image.revision"] = old
    state = tmp_path / "state.json"
    state.write_text(json.dumps({"app": app, "proxy": proxy, "image": image, "sha": old,
                                 "old": old, "target": target, "images": {IMAGE: old}}))
    (binaries / "docker").write_text('''#!/usr/bin/env python3
import json, os, subprocess, sys
from pathlib import Path
path = Path(os.environ['FAKE_STATE'])
s = json.loads(path.read_text())
a = sys.argv[1:]
mode = os.environ['FAKE_MODE']
sha = s['sha']
image_id = s['app']['Image']
health = 'unhealthy' if mode == 'current_unhealthy' or (mode == 'candidate_unhealthy' and sha == s['target']) else 'healthy'
s['app']['State']['Health']['Status'] = health
s['app']['Config']['Labels']['org.opencontainers.image.revision'] = sha
event = {'action': 'docker', 'args': a, 'checkout': subprocess.check_output(['git','-C',os.environ['APP_DIR'],'rev-parse','HEAD'], text=True).strip(),
         'checkout_has_helper': (Path(os.environ['APP_DIR'])/'deploy/vps/runtime_compose_context.py').exists()}
if a[0] == 'compose':
    event['project'] = os.environ['COMPOSE_PROJECT_NAME']
    event['override'] = json.loads(Path(os.environ['COMPOSE_FILE'].split(':')[-1]).read_text())
with open(os.environ['FAKE_LOG'], 'a') as f: f.write(json.dumps(event)+'\\n')
if a[:2] == ['container', 'inspect']:
    print(json.dumps([s['proxy'] if a[-1] == 'sharipovai-caddy' else s['app']]))
elif a[:2] == ['image', 'inspect']:
    revision = s['images'].get(a[-1])
    if revision is None: sys.exit(1)
    if '-f' in a: print(revision)
    else: print(json.dumps([{'Id': a[-1], 'Config': {'Labels': {'org.opencontainers.image.revision': revision}}}]))
elif a[0] == 'inspect':
    fmt = a[2]
    if 'RestartCount' in fmt:
        print('running '+health+' 0 0 false')
    else:
        print(image_id if fmt == '{{.Image}}' else sha if 'revision' in fmt else health)
elif a[0] == 'exec':
    assert a[1:] == ['sharipovai','printenv','SHARIPOVAI_BUILD_SHA']
    print(sha)
elif a[0] == 'tag':
    s['images'][a[2]] = s['images'][a[1]]
elif a[0] == 'compose':
    if 'config' in a:
        env = dict(x.split('=',1) for x in s['app']['Config']['Env'])
        if mode == 'unsafe_target': env['TESTNET_EXECUTION_ENABLED'] = '1'
        print(json.dumps({'services': {'sharipovai': {'environment': env}}}))
    elif 'build' in a:
        assert a[-1] == 'sharipovai'
        s['images']['sharipovai:'+os.environ['SHARIPOVAI_RELEASE_TAG']] = os.environ['SHARIPOVAI_RELEASE_SHA']
    elif 'up' in a:
        assert a == ['compose','up','-d','--no-deps','--no-build','sharipovai']
        s['sha'] = os.environ['SHARIPOVAI_RELEASE_SHA']
        s['app']['Image'] = 'sha256:'+ ('c' if s['sha'] == s['target'] else 'b')*64
        s['images'][s['app']['Image']] = s['sha']
        s['app']['Config']['Env'] = [x for x in s['app']['Config']['Env'] if not x.startswith('SHARIPOVAI_BUILD_SHA=')] + ['SHARIPOVAI_BUILD_SHA='+s['sha']]
        if mode == 'volume_drift':
            s['app']['Mounts'][0]['Name'] = 'wrong-volume' if s['sha'] == s['target'] else 'retained-data'
    elif a != ['compose','ps']: raise AssertionError(a)
else: raise AssertionError(a)
path.write_text(json.dumps(s))
''')
    (binaries / "curl").write_text('#!/bin/sh\n[ "$FAKE_MODE" != "http_failure" ] || exit 22\nprintf 200\n')
    for p in binaries.iterdir(): p.chmod(0o700)
    script = tmp_path / "updater.sh"
    # GitHub-hosted workers are unprivileged. Only bypass the root guard in this
    # disposable fixture copy; every Docker/HTTP operation is a strict local fake.
    script.write_text((ROOT / "deploy/vps/update_from_main.sh").read_text().replace(
        "[[ ${EUID} -eq 0 ]] || fail 'run as root'", ": # isolated fixture root guard"))
    env = {**os.environ, "PATH": str(binaries) + os.pathsep + os.environ['PATH'],
           "APP_DIR": str(checkout), "LOCK_FILE": str(tmp_path / "deploy.lock"), "BRANCH": "main", "FETCH_REMOTE": "origin",
           "FAKE_STATE": str(state), "FAKE_LOG": str(tmp_path / "events.jsonl"), "FAKE_MODE": mode,
           "HEALTH_TIMEOUT_SECONDS": "2", "HEALTH_DELAY_SECONDS": "0.1", "SHARIPOVAI_EXPECTED_TARGET_SHA": target}
    return checkout, script, env, old, target


@pytest.mark.parametrize("mode", ["ok", "candidate_unhealthy", "volume_drift"])
def test_target_helper_bootstraps_old_checkout_and_rollback_uses_same_context(tmp_path, mode):
    checkout, script, env, old, target = _bootstrap_fixture(tmp_path, mode=mode)
    assert not (checkout / "deploy/vps/runtime_compose_context.py").exists()
    result = subprocess.run(["bash", str(script)], env=env, capture_output=True, text=True, timeout=30)
    assert (result.returncode == 0) == (mode == "ok"), result.stdout + result.stderr
    assert _git(checkout, "rev-parse", "HEAD") == (target if mode == "ok" else old)
    events = [json.loads(line) for line in Path(env["FAKE_LOG"]).read_text().splitlines()]
    capture = next(e for e in events if e.get("args") == ["container", "inspect", "sharipovai"])
    assert capture["checkout"] == old and not capture["checkout_has_helper"]
    tag_index = next(i for i, e in enumerate(events) if e.get("args", [""])[0] == "tag")
    assert tag_index < next(i for i, e in enumerate(events) if e["action"] == "preflight")
    assert tag_index < next(i for i, e in enumerate(events) if e["action"] == "backup")
    assert events[tag_index]["checkout"] == old
    composed = [e for e in events if e.get("args", [""])[0] == "compose"]
    for event in composed:
        assert event["project"] == "sharipovai-runtime-123"
        assert event["override"] == runtime_context(*runtime(), SHA)["override"]
    assert sum("build" in e["args"] for e in composed) == 1
    assert sum("up" in e["args"] for e in composed) == (1 if mode == "ok" else 2)


@pytest.mark.parametrize("mode", ["current_unhealthy", "http_failure", "unsafe_target", "wrong_target", "invalid_helper"])
def test_bootstrap_blocks_before_checkout_mutation_on_failed_gate(tmp_path, mode):
    checkout, script, env, old, target = _bootstrap_fixture(tmp_path, mode=mode, broken_helper=mode == "invalid_helper")
    if mode == "wrong_target": env["SHARIPOVAI_EXPECTED_TARGET_SHA"] = "f" * 40
    result = subprocess.run(["bash", str(script)], env=env, capture_output=True, text=True, timeout=30)
    assert result.returncode != 0
    assert _git(checkout, "rev-parse", "HEAD") == old
    assert not (checkout / "deploy/vps/runtime_compose_context.py").exists()
    log = Path(env["FAKE_LOG"])
    events = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
    assert not any(e["action"] == "backup" or "up" in e.get("args", []) or "build" in e.get("args", []) for e in events)
