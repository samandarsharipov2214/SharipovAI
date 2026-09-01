from __future__ import annotations

import fcntl
import json
import os
from pathlib import Path
import subprocess

from autonomous_trading.storage_budget_v2 import StorageClass, retention_decision


ROOT = Path(__file__).resolve().parents[1]
PRUNE = ROOT / "deploy" / "vps" / "prune_disposable_disk.sh"
GUARD = ROOT / "scripts" / "deploy_storage_guard.sh"
HEALER = ROOT / "deploy" / "vps" / "self-healing-run.sh"
CLEANUP_V2 = ROOT / "autonomous_trading" / "storage_cleanup_v2.py"

LIVE_ID = "sha256:" + "a" * 64
ROLLBACK_ID = "sha256:" + "b" * 64
OLD_ID = "sha256:" + "c" * 64
HEX12_ID = "sha256:" + "d" * 64
CADDY_ID = "sha256:" + "e" * 64
LOCAL_ID = "sha256:" + "f" * 64

FAKE_DOCKER = r"""#!/usr/bin/env python3
import json
import os
import sys
from pathlib import Path

log_path = Path(os.environ["FAKE_DOCKER_LOG"])
state_path = Path(os.environ["FAKE_DOCKER_STATE"])
log_path.write_text(log_path.read_text(encoding="utf-8") + " ".join(sys.argv[1:]) + "\n", encoding="utf-8")
state = json.loads(state_path.read_text(encoding="utf-8"))
args = sys.argv[1:]

def fail(code=1):
    raise SystemExit(code)

if args[:2] == ["system", "df"]:
    print("TYPE TOTAL ACTIVE SIZE RECLAIMABLE")
    raise SystemExit(0)

if args[:2] == ["inspect", "-f"] and len(args) >= 4:
    fmt, target = args[2], args[3]
    containers = state["containers"]
    obj = containers.get(target)
    if obj is None:
        for item in containers.values():
            if item.get("Id") == target or item.get("Name") == target:
                obj = item
                break
    if obj is None:
        fail(1)
    if fmt == "{{.Image}}":
        print(obj["Image"])
        raise SystemExit(0)
    if fmt == "{{.Image}}|{{.Created}}|{{.State.Running}}":
        running = "true" if obj["Running"] else "false"
        print(f"{obj['Image']}|{obj['Created']}|{running}")
        raise SystemExit(0)
    fail(1)

if args[:1] == ["ps"]:
    for name, obj in state["containers"].items():
        print(f"{name}|{obj['Id']}")
    raise SystemExit(0)

if args[:1] == ["images"]:
    for image in state["images"]:
        repo, tag = image["RepoTags"][0].split(":", 1)
        print(f"{image['Id']}|{repo}|{tag}")
    raise SystemExit(0)

if args[:3] == ["image", "inspect", "-f"] and len(args) >= 5:
    fmt, target = args[3], args[4]
    for image in state["images"]:
        if image["Id"] == target:
            print(f"{image['Size']}|{image['Created']}")
            raise SystemExit(0)
    fail(1)

if args[:2] == ["image", "rm"]:
    target = args[2]
    live = {state["containers"]["sharipovai"]["Image"], state["containers"]["sharipovai-caddy"]["Image"]}
    if target in live:
        fail(1)
    state.setdefault("removed", []).append(target)
    state["images"] = [image for image in state["images"] if image["Id"] != target]
    state_path.write_text(json.dumps(state), encoding="utf-8")
    raise SystemExit(0)

if args[:2] == ["builder", "prune"] and args[2:] == ["-f"]:
    print("Total: 0B")
    raise SystemExit(0)

if args[:2] == ["system", "prune"] or args[:2] == ["volume", "prune"] or args[:2] == ["volume", "rm"]:
    fail(99)

fail(91)
"""


def _state() -> dict:
    return {
        "containers": {
            "sharipovai": {
                "Id": "ctr-live",
                "Image": LIVE_ID,
                "Created": "2026-09-01T00:00:00Z",
                "Running": True,
            },
            "sharipovai-caddy": {
                "Id": "ctr-caddy",
                "Image": CADDY_ID,
                "Created": "2026-09-01T00:00:00Z",
                "Running": True,
            },
            "sharipovai-rollback-111": {
                "Id": "ctr-rollback",
                "Image": ROLLBACK_ID,
                "Created": "2026-08-15T00:00:00Z",
                "Running": False,
            },
        },
        "images": [
            {
                "Id": LIVE_ID,
                "RepoTags": ["sharipovai:deploy-aaaaaaaaaaaa-1-1"],
                "Size": 111,
                "Created": "2026-09-01T00:00:00Z",
            },
            {
                "Id": ROLLBACK_ID,
                "RepoTags": ["sharipovai:deploy-bbbbbbbbbbbb-1-1"],
                "Size": 222,
                "Created": "2026-08-15T00:00:00Z",
            },
            {
                "Id": OLD_ID,
                "RepoTags": ["sharipovai:deploy-cccccccccccc-1-1"],
                "Size": 333,
                "Created": "2026-07-01T00:00:00Z",
            },
            {
                "Id": HEX12_ID,
                "RepoTags": ["sharipovai:dddddddddddd"],
                "Size": 444,
                "Created": "2026-06-01T00:00:00Z",
            },
            {
                "Id": LOCAL_ID,
                "RepoTags": ["sharipovai:local"],
                "Size": 555,
                "Created": "2026-05-01T00:00:00Z",
            },
            {
                "Id": CADDY_ID,
                "RepoTags": ["caddy:2-alpine"],
                "Size": 666,
                "Created": "2026-09-01T00:00:00Z",
            },
        ],
        "removed": [],
    }


def _runtime(tmp_path: Path, state: dict | None = None) -> tuple[dict[str, str], Path, Path, Path]:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    docker_log = tmp_path / "docker.log"
    docker_log.write_text("", encoding="utf-8")
    state_path = tmp_path / "docker-state.json"
    state_path.write_text(json.dumps(state or _state()), encoding="utf-8")
    docker = fake_bin / "docker"
    docker.write_text(FAKE_DOCKER, encoding="utf-8")
    docker.chmod(0o755)

    backups = tmp_path / "backups"
    backups.mkdir()
    host_log = tmp_path / "self-healing-host.log"
    host_log.write_text("ok\n", encoding="utf-8")

    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{fake_bin}{os.pathsep}{env.get('PATH', '/usr/bin:/bin')}",
            "FAKE_DOCKER_LOG": str(docker_log),
            "FAKE_DOCKER_STATE": str(state_path),
            "SHARIPOVAI_REPO_DIR": str(tmp_path),
            "SHARIPOVAI_DEPLOY_ROOT": str(tmp_path),
            "SHARIPOVAI_BACKUP_DIR": str(backups),
            "SELF_HEALING_HOST_LOG": str(host_log),
            "KEEP": "7",
        }
    )
    return env, docker_log, state_path, backups


def _run(env: dict[str, str], *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(PRUNE), *args],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def _plan_lines(output: str) -> list[str]:
    return [line for line in output.splitlines() if line.startswith("PRUNE_PLAN ")]


def test_scripts_have_valid_bash_syntax() -> None:
    for script in (PRUNE, GUARD, HEALER):
        result = subprocess.run(["bash", "-n", str(script)], capture_output=True, text=True)
        assert result.returncode == 0, result.stderr


def test_scripts_forbid_unbounded_prune_and_volume_deletion() -> None:
    prune = PRUNE.read_text(encoding="utf-8")
    guard = GUARD.read_text(encoding="utf-8")
    healer = HEALER.read_text(encoding="utf-8")
    cleanup = CLEANUP_V2.read_text(encoding="utf-8")
    joined = "\n".join((prune, guard, healer, cleanup))
    for forbidden in (
        "docker system prune -a",
        "docker system prune --all",
        "docker volume prune",
        "docker volume rm",
        "docker container prune",
        "docker buildx prune",
        "docker builder prune -a",
        "docker builder prune --all",
    ):
        assert forbidden not in joined
    for forbidden in ("paper_trades", "autonomous_paper_state", "docker rm ", "git reset --hard"):
        assert forbidden not in prune
        assert forbidden not in guard
    assert "docker builder prune -f" in prune
    assert "docker image rm" in prune
    assert "prune_disposable_disk" in healer
    assert "STORAGE_GUARD_CLEANUP_SKIPPED" not in guard


def test_python_cleanup_contract_still_never_auto_deletes_backups() -> None:
    for storage_class in (
        StorageClass.BACKUP,
        StorageClass.PRODUCTION_STATE,
        StorageClass.EVIDENCE,
        StorageClass.ROLLBACK,
    ):
        decision = retention_decision(storage_class)
        assert decision.automatic_cleanup_allowed is False


def test_dry_run_parser_never_targets_live_image_volume_or_paper_db(tmp_path: Path) -> None:
    env, docker_log, _state_path, backups = _runtime(tmp_path)
    (backups / "paper_trades.db").write_text("paper", encoding="utf-8")
    (backups / "autonomous_paper_state.json").write_text("{}", encoding="utf-8")
    (backups / "sharipovai_data").write_text("volume-name-trap", encoding="utf-8")
    latest = backups / "sharipovai-20260901T000000Z.tar.gz"
    latest.write_text("verified", encoding="utf-8")
    (backups / "latest.tar.gz").symlink_to(latest.name)

    result = _run(env, "--dry-run")
    assert result.returncode == 0, result.stderr
    assert "PRUNE_DRY_RUN=1" in result.stdout
    plan = "\n".join(_plan_lines(result.stdout))
    assert LIVE_ID not in plan
    assert ROLLBACK_ID not in plan
    assert CADDY_ID not in plan
    assert LOCAL_ID not in plan
    assert OLD_ID in plan
    assert HEX12_ID in plan
    assert "sharipovai:local" not in plan
    assert "sharipovai_data" not in plan
    assert "caddy_data" not in plan
    assert "paper_trades" not in plan
    assert "autonomous_paper_state" not in plan
    assert ".db" not in plan
    assert "latest.tar.gz" not in plan
    assert str(latest) not in plan
    docker_calls = docker_log.read_text(encoding="utf-8")
    assert "image rm" not in docker_calls
    assert "builder prune" not in docker_calls
    assert "volume" not in docker_calls
    assert "system prune" not in docker_calls


def test_fail_closed_skips_image_delete_when_live_inspect_fails(tmp_path: Path) -> None:
    state = _state()
    del state["containers"]["sharipovai"]
    env, docker_log, _state_path, _backups = _runtime(tmp_path, state)
    result = _run(env, "--dry-run")
    assert result.returncode == 0, result.stderr
    assert "PRUNE_IMAGES_FAIL_CLOSED" in result.stdout
    assert "reason=live_image_unknown" in result.stdout
    plan = "\n".join(_plan_lines(result.stdout))
    assert LIVE_ID not in plan
    assert OLD_ID not in plan
    assert "image rm" not in docker_log.read_text(encoding="utf-8")


def test_keep_backups_are_not_deleted_below_keep_count(tmp_path: Path) -> None:
    env, _docker_log, _state_path, backups = _runtime(tmp_path)
    # Image inspect will fail-closed independently; backups still honor KEEP.
    files = []
    for index in range(10):
        path = backups / f"sharipovai-2026080{index}T000000Z.tar.gz"
        path.write_text(f"archive-{index}", encoding="utf-8")
        os.utime(path, (1_700_000_000 + index, 1_700_000_000 + index))
        files.append(path)
    current = files[-1]
    (backups / "latest.tar.gz").symlink_to(current.name)

    env["KEEP"] = "7"
    result = _run(env)
    assert result.returncode == 0, result.stderr
    remaining = sorted(p.name for p in backups.glob("sharipovai-*.tar.gz"))
    assert len(remaining) == 7
    assert current.name in remaining
    assert (backups / "latest.tar.gz").exists()
    assert "PRUNE_KEEP kind=backup" in result.stdout
    assert f"path={current}" in result.stdout or "reason=current_verified" in result.stdout


def test_keep_backups_with_fewer_than_keep_are_untouched(tmp_path: Path) -> None:
    env, _docker_log, _state_path, backups = _runtime(tmp_path)
    for index in range(5):
        path = backups / f"sharipovai-2026070{index}T000000Z.tar.gz"
        path.write_text(f"archive-{index}", encoding="utf-8")
        os.utime(path, (1_700_000_000 + index, 1_700_000_000 + index))
    result = _run(env)
    assert result.returncode == 0, result.stderr
    remaining = list(backups.glob("sharipovai-*.tar.gz"))
    assert len(remaining) == 5
    assert not any(line.startswith("PRUNE_PLAN kind=backup") for line in result.stdout.splitlines())


def test_expired_staging_is_removed_only_when_export_lock_is_free(tmp_path: Path) -> None:
    env, _docker_log, _state_path, backups = _runtime(tmp_path)
    staging = backups / ".staging-stale"
    staging.mkdir()
    (staging / "chunk").write_text("junk", encoding="utf-8")

    result = _run(env, "--dry-run")
    assert result.returncode == 0, result.stderr
    assert any("kind=staging" in line and "PRUNE_PLAN" in line for line in result.stdout.splitlines())
    assert staging.is_dir()

    result = _run(env)
    assert result.returncode == 0, result.stderr
    assert not staging.exists()

    staging.mkdir()
    lock = backups / ".export.lock"
    with lock.open("w", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        held = _run(env)
        assert held.returncode == 0, held.stderr
        assert "reason=export_lock_held" in held.stdout
        assert staging.is_dir()
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def test_host_log_is_truncated_to_keep_window(tmp_path: Path) -> None:
    env, _docker_log, _state_path, _backups = _runtime(tmp_path)
    host_log = Path(env["SELF_HEALING_HOST_LOG"])
    host_log.write_bytes(b"x" * 250)
    env["SELF_HEALING_HOST_LOG_KEEP_BYTES"] = "100"
    result = _run(env)
    assert result.returncode == 0, result.stderr
    assert host_log.stat().st_size == 100
    assert "PRUNE_PLAN kind=host_log" in result.stdout
    assert "bytes=150" in result.stdout
    reclaimed = int(
        next(
            line.split("=", 1)[1]
            for line in result.stdout.splitlines()
            if line.startswith("PRUNE_DISPOSABLE_DISK_RECLAIMED_BYTES=")
        )
    )
    assert reclaimed >= 150


def test_non_dry_run_removes_only_unused_disposable_images(tmp_path: Path) -> None:
    env, docker_log, state_path, _backups = _runtime(tmp_path)
    result = _run(env)
    assert result.returncode == 0, result.stderr
    state = json.loads(state_path.read_text(encoding="utf-8"))
    remaining = {image["Id"] for image in state["images"]}
    assert LIVE_ID in remaining
    assert ROLLBACK_ID in remaining
    assert CADDY_ID in remaining
    assert LOCAL_ID in remaining
    assert OLD_ID not in remaining
    assert HEX12_ID not in remaining
    calls = docker_log.read_text(encoding="utf-8")
    assert "image rm " + OLD_ID in calls
    assert "image rm " + HEX12_ID in calls
    assert "image rm " + LIVE_ID not in calls
    assert "builder prune -f" in calls
    assert "system prune" not in calls
    assert "volume" not in calls


def test_storage_guard_and_healer_wire_the_same_helper() -> None:
    guard = GUARD.read_text(encoding="utf-8")
    healer = HEALER.read_text(encoding="utf-8")
    assert "prune_disposable_disk.sh" in guard
    assert "prune_disposable_disk.sh" in healer
    assert "run_bounded_disposable_prune" in guard
    assert "prune_disposable_disk)" in healer
    assert 'log "Executing allow-listed action: prune_disposable_disk"' in healer
