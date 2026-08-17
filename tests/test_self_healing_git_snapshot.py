from __future__ import annotations

from pathlib import Path
import stat
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import self_healing_agent as agent  # noqa: E402
import self_healing_runner as runner  # noqa: E402


def _git(repo: Path, *args: str, env: dict[str, str] | None = None) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )
    return result.stdout.strip()


def _trusted_clone(source: Path, destination: Path) -> tuple[Path, str]:
    head = _git(source, "rev-parse", "HEAD")
    subprocess.run(
        ["git", "clone", "--quiet", "--no-checkout", "--no-hardlinks", str(source), str(destination)],
        check=True,
    )
    git_dir = destination / ".git"
    subprocess.run(
        ["git", f"--git-dir={git_dir}", "read-tree", head],
        check=True,
    )
    subprocess.run(
        ["git", f"--git-dir={git_dir}", "config", "core.filemode", "false"],
        check=True,
    )
    return git_dir, head


def _config(tmp_path: Path, repo: Path) -> agent.Config:
    data = tmp_path / "data"
    work = data / ".self_healing"
    data.mkdir(exist_ok=True)
    return agent.Config(
        repo_dir=repo,
        data_dir=data,
        work_dir=work,
        log_file=data / "agent.log",
        state_file=work / "state.json",
        lock_file=work / "agent.lock",
        host_status_file=work / "container_status.json",
        host_logs_file=work / "docker_logs_15m.log",
        action_file=work / "action",
        action_meta_file=work / "action.json",
        expected_sha_file=work / "expected_sha",
        db_path=data / "sharipovai_shared.db",
        backup_path=tmp_path / "latest.tar.gz",
        restore_candidate=work / "restore_candidate.db",
        health_url="http://127.0.0.1:1/health",
        websocket_url="http://127.0.0.1:1/ws",
        request_timeout_seconds=0.1,
        pytest_timeout_seconds=30,
        websocket_alert_after_seconds=300,
        alert_cooldown_seconds=3600,
        restart_cooldown_seconds=1800,
        max_related_tests=25,
        max_log_bytes=1024 * 1024,
    )


def test_trusted_copy_materializes_git_head_without_recursive_source_copy(
    tmp_path: Path,
    monkeypatch,
) -> None:
    source = tmp_path / "source"
    destination = tmp_path / "destination"
    trusted = tmp_path / "trusted"
    source.mkdir()
    _git(source, "init", "-b", "main")
    _git(source, "config", "user.name", "SharipovAI CI")
    _git(source, "config", "user.email", "ci@example.invalid")
    (source / "module.py").write_text("VALUE = 1\n", encoding="utf-8")
    (source / "unchanged.py").write_text("UNCHANGED = True\n", encoding="utf-8")
    _git(source, "add", "module.py", "unchanged.py")
    _git(source, "commit", "-m", "initial")
    _git(source, "pack-refs", "--all", "--prune")

    trusted_git, _head = _trusted_clone(source, trusted)
    (source / "module.py").write_text("VALUE = 2\n", encoding="utf-8")
    (source / ".env.production").write_text("SECRET=do-not-copy\n", encoding="utf-8")

    packed_refs = source / ".git" / "packed-refs"
    original_mode = stat.S_IMODE(packed_refs.stat().st_mode)
    packed_refs.chmod(0)

    original_copytree = runner.shutil.copytree

    def guarded_copytree(src, dst, *args, **kwargs):
        if Path(src).resolve() == source.resolve():
            raise AssertionError("production source tree must never be recursively copied")
        return original_copytree(src, dst, *args, **kwargs)

    monkeypatch.setattr(runner.shutil, "copytree", guarded_copytree)
    monkeypatch.setenv("GIT_DIR", str(trusted_git))
    monkeypatch.setenv("GIT_WORK_TREE", str(source))
    try:
        runner._trusted_copy_repository_snapshot(source, destination)
    finally:
        packed_refs.chmod(original_mode)

    assert (destination / "module.py").read_text(encoding="utf-8") == "VALUE = 2\n"
    assert (destination / "unchanged.py").read_text(encoding="utf-8") == "UNCHANGED = True\n"
    assert (destination / ".git" / "HEAD").is_file()
    assert not (destination / ".env.production").exists()


def test_trusted_copy_does_not_need_to_open_unrelated_unreadable_tracked_file(
    tmp_path: Path,
    monkeypatch,
) -> None:
    source = tmp_path / "source"
    destination = tmp_path / "destination"
    trusted = tmp_path / "trusted"
    source.mkdir()
    _git(source, "init", "-b", "main")
    _git(source, "config", "user.name", "SharipovAI CI")
    _git(source, "config", "user.email", "ci@example.invalid")
    (source / "changed.py").write_text("VALUE = 1\n", encoding="utf-8")
    locked = source / "locked.py"
    locked.write_text("LOCKED = True\n", encoding="utf-8")
    _git(source, "add", "changed.py", "locked.py")
    _git(source, "commit", "-m", "initial")

    trusted_git, _head = _trusted_clone(source, trusted)
    (source / "changed.py").write_text("VALUE = 2\n", encoding="utf-8")
    original_mode = stat.S_IMODE(locked.stat().st_mode)
    locked.chmod(0)
    monkeypatch.setenv("GIT_DIR", str(trusted_git))
    monkeypatch.setenv("GIT_WORK_TREE", str(source))
    try:
        runner._trusted_copy_repository_snapshot(source, destination)
    finally:
        locked.chmod(original_mode)

    assert (destination / "changed.py").read_text(encoding="utf-8") == "VALUE = 2\n"
    assert (destination / "locked.py").read_text(encoding="utf-8") == "LOCKED = True\n"


def test_changed_unreadable_file_fails_closed_with_precise_reason(
    tmp_path: Path,
    monkeypatch,
) -> None:
    source = tmp_path / "source"
    destination = tmp_path / "destination"
    trusted = tmp_path / "trusted"
    source.mkdir()
    _git(source, "init", "-b", "main")
    _git(source, "config", "user.name", "SharipovAI CI")
    _git(source, "config", "user.email", "ci@example.invalid")
    changed = source / "changed.py"
    changed.write_text("VALUE = 1\n", encoding="utf-8")
    _git(source, "add", "changed.py")
    _git(source, "commit", "-m", "initial")

    trusted_git, _head = _trusted_clone(source, trusted)
    changed.write_text("VALUE = 2\n", encoding="utf-8")
    original_mode = stat.S_IMODE(changed.stat().st_mode)
    changed.chmod(0)
    monkeypatch.setenv("GIT_DIR", str(trusted_git))
    monkeypatch.setenv("GIT_WORK_TREE", str(source))
    try:
        with pytest.raises(RuntimeError, match="unreadable|Git inspection failed"):
            runner._trusted_copy_repository_snapshot(source, destination)
    finally:
        changed.chmod(original_mode)


def test_agent_uses_external_git_snapshot_when_host_packed_refs_is_unreadable(
    tmp_path: Path,
    monkeypatch,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.name", "SharipovAI CI")
    _git(repo, "config", "user.email", "ci@example.invalid")
    (repo / "module.py").write_text("VALUE = 1\n", encoding="utf-8")
    _git(repo, "add", "module.py")
    _git(repo, "commit", "-m", "initial")
    _git(repo, "pack-refs", "--all", "--prune")

    trusted = tmp_path / "trusted"
    trusted_git, head = _trusted_clone(repo, trusted)

    # Create an actual worktree change that Self-Healing must discover and
    # compile. The protected host metadata is then made unreadable.
    (repo / "module.py").write_text("VALUE = 2\n", encoding="utf-8")
    packed_refs = repo / ".git" / "packed-refs"
    original_mode = stat.S_IMODE(packed_refs.stat().st_mode)
    packed_refs.chmod(0)

    original_copy = agent.copy_repository_snapshot
    monkeypatch.setenv("GIT_DIR", str(trusted_git))
    monkeypatch.setenv("GIT_WORK_TREE", str(repo))
    monkeypatch.setenv("SELF_HEALING_REPO_DIR", str(repo))
    try:
        runner.install_trusted_git_snapshot()
        instance = agent.SelfHealingAgent(_config(tmp_path, repo))
        instance.check_changed_modules()
    finally:
        agent.copy_repository_snapshot = original_copy
        packed_refs.chmod(original_mode)

    assert instance.unresolved == []
    assert instance.state.value["last_tested_sha"] == head
    assert instance.state.value["last_pytest_ok_at"]


def test_production_supervisor_wires_snapshot_without_relaxing_host_git_permissions() -> None:
    supervisor = ROOT / "deploy" / "vps" / "self-healing-run.sh"
    helper = ROOT / "tools" / "self_healing_git_snapshot.sh"
    runner_path = ROOT / "tools" / "self_healing_runner.py"

    subprocess.run(["bash", "-n", str(supervisor)], check=True)
    subprocess.run(["bash", "-n", str(helper)], check=True)

    supervisor_text = supervisor.read_text(encoding="utf-8")
    helper_text = helper.read_text(encoding="utf-8")
    runner_text = runner_path.read_text(encoding="utf-8")

    assert "prepare_git_snapshot" in supervisor_text
    assert '-e GIT_DIR="$GIT_SNAPSHOT_DIR"' in supervisor_text
    assert "-e GIT_WORK_TREE=/workspace" in supervisor_text
    assert 'python "$AGENT_RUNNER_PATH"' in supervisor_text
    assert "--no-hardlinks" in helper_text
    assert 'docker exec -i --user "$CONTAINER_USER"' in helper_text
    assert "chmod -R u+rwX,go-rwx" in helper_text
    assert "\\$next" in helper_text
    assert "filemode = false" in helper_text
    assert 'read-tree "$HEAD_SHA"' in helper_text
    assert 'destination / ".git"' in runner_text
    assert '"checkout-index"' in runner_text
    assert "shutil.copytree(source" not in runner_text

    # The fix is a private readable copy. It must never broaden ownership or
    # mode bits on the real host repository metadata.
    forbidden = (
        'chmod "$REPO_DIR/.git',
        "chmod '$REPO_DIR/.git",
        'chown "$REPO_DIR/.git',
        "chown '$REPO_DIR/.git",
    )
    assert not any(token in supervisor_text or token in helper_text for token in forbidden)
