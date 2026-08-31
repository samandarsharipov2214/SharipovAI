import json
import os
import subprocess
import uuid
from pathlib import Path

import pytest


WATCHER = Path("deploy/vps/sharipovai-deploy-watcher")
INSTALLED_SOURCE = Path("scripts/sharipovai_deploy_watcher.sh")
WATCHERS = (WATCHER, INSTALLED_SOURCE)


def _run_lifecycle(
    tmp_path: Path,
    *,
    watcher: Path,
    request_id: str,
    deploy_result: int,
) -> tuple[subprocess.CompletedProcess[str], Path, list[str]]:
    trace = tmp_path / "trace.log"
    temp_trace = tmp_path / "temp.log"
    temp_root = tmp_path / "private-tmp"
    temp_root.mkdir()
    request = {
        "request_id": request_id,
        "action": "deploy_main",
        "actor_id": 1,
        "chat_id": 1,
        "created_at": int(__import__("time").time()),
    }
    script = r'''
set -Eeuo pipefail
export SHARIPOVAI_DEPLOY_WATCHER_LIBRARY=1
source "$1"
validate_owner_request() { return 0; }
fetch_main() {
  printf 'path=%s\nmode=%s\n' "$output_file" "$(stat -c '%a' "$output_file")" >> "$TEMP_TRACE"
}
git() { echo 96296887; }
write_status() { printf '%s|%s\n' "$1" "$2" >> "$TRACE"; }
remove_request() { echo removed >> "$TRACE"; }
notify() { :; }
run_deploy_with_watchdog() { printf 'bounded deploy output\n'; return "$DEPLOY_RESULT"; }
process_request "$REQUEST"
'''
    result = subprocess.run(
        ["bash", "-c", script, "watcher", str(watcher)],
        env=os.environ
        | {
            "DEPLOY_RESULT": str(deploy_result),
            "REQUEST": json.dumps(request),
            "TEMP_TRACE": str(temp_trace),
            "TMPDIR": str(temp_root),
            "TRACE": str(trace),
        },
        text=True,
        capture_output=True,
        check=False,
    )
    temp_lines = temp_trace.read_text(encoding="utf-8").splitlines() if temp_trace.exists() else []
    return result, trace, temp_lines


def _created_path(temp_lines: list[str]) -> Path:
    line = next(item for item in temp_lines if item.startswith("path="))
    return Path(line.removeprefix("path="))


def test_deploy_watcher_keeps_stdin_attached_for_python_heredocs() -> None:
    source = WATCHER.read_text(encoding="utf-8")

    assert 'docker exec -i "$SERVICE" python - <<\'PY\'' in source
    assert 'docker exec -i \\\n    -e DEPLOY_STATE="$state"' in source
    assert 'docker exec "$SERVICE" python - <<\'PY\'' not in source


def test_deploy_watcher_remains_main_only_and_owner_requested() -> None:
    source = WATCHER.read_text(encoding="utf-8")

    assert 'if [[ "$action" != "deploy_main" ]]' in source
    assert 'git fetch --no-tags "${FETCH_REMOTE}" main' in source
    assert 'git checkout -q main' in source
    assert 'SHARIPOVAI_DEPLOY_WATCHER_ACTIVE=1' in source
    assert 'heartbeat_loop()' in source
    assert 'run_deploy_with_watchdog()' in source
    assert 'timeout timed_out' in source


def test_watcher_independently_validates_persisted_owner_before_any_fetch() -> None:
    source = WATCHER.read_text(encoding="utf-8")

    assert 'owner.json' in source
    assert 'actor != owner_user or chat != owner_chat' in source
    assert 'if ! validate_owner_request "$request_json"; then' in source
    validation = source.index('if ! validate_owner_request "$request_json"; then')
    private_execution = source.index('run_deploy_request_with_private_output "$request_id" "$chat_id"', validation)
    assert validation < private_execution
    helper = source.split("run_deploy_request_with_private_output() (", 1)[1].split("\nprocess_request()", 1)[0]
    assert 'if ! fetch_main >"$output_file" 2>&1; then' in helper


def test_unauthorized_requests_never_call_fetch_main(tmp_path: Path) -> None:
    trace = tmp_path / "fetches.log"
    script = r'''
set -Eeuo pipefail
export SHARIPOVAI_DEPLOY_WATCHER_LIBRARY=1
source "$1"
fetch_main() { echo fetch >> "$TRACE"; }
validate_owner_request() { return 1; }
write_status() { :; }
remove_request() { :; }
notify() { :; }
process_request "$REQUEST"
'''
    requests = [
        {"request_id": "wrong-actor", "action": "deploy_main", "actor_id": 2, "chat_id": 1, "created_at": 1},
        {"request_id": "wrong-chat", "action": "deploy_main", "actor_id": 1, "chat_id": 2, "created_at": 1},
        {"request_id": "missing-identity", "action": "deploy_main", "created_at": 1},
        {"request_id": "malformed-owner", "action": "deploy_main", "actor_id": 1, "chat_id": 1, "created_at": 1},
    ]
    for request in requests:
        environment = os.environ | {"TRACE": str(trace), "REQUEST": json.dumps(request)}
        result = subprocess.run(
            ["bash", "-c", script, "watcher", str(WATCHER)],
            env=environment,
            text=True,
            capture_output=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr

    assert not trace.exists(), "unauthorized request reached fetch_main"


@pytest.mark.parametrize("watcher", WATCHERS)
def test_watcher_records_terminal_timeout_and_removes_request(tmp_path: Path, watcher: Path) -> None:
    result, trace, _ = _run_lifecycle(
        tmp_path,
        watcher=watcher,
        request_id="timeout-request",
        deploy_result=124,
    )

    assert result.returncode == 0, result.stderr
    assert "timeout|timed_out" in trace.read_text(encoding="utf-8")
    assert "removed" in trace.read_text(encoding="utf-8")


@pytest.mark.parametrize("watcher", WATCHERS)
def test_private_output_ignores_legacy_collision_and_cleans_up(tmp_path: Path, watcher: Path) -> None:
    request_id = f"timeout-request-{uuid.uuid4().hex}"
    legacy = Path("/tmp") / f"{request_id}.log"
    legacy.write_text("owner evidence must survive", encoding="utf-8")
    try:
        result, trace, temp_lines = _run_lifecycle(
            tmp_path,
            watcher=watcher,
            request_id=request_id,
            deploy_result=124,
        )
        created = _created_path(temp_lines)

        assert result.returncode == 0, result.stderr
        assert legacy.read_text(encoding="utf-8") == "owner evidence must survive"
        assert created != legacy
        assert request_id not in created.name
        assert "mode=600" in temp_lines
        assert not created.exists()
        assert "timeout|timed_out" in trace.read_text(encoding="utf-8")
        assert "removed" in trace.read_text(encoding="utf-8")
    finally:
        legacy.unlink(missing_ok=True)


@pytest.mark.parametrize("watcher", WATCHERS)
def test_private_output_does_not_follow_legacy_symlink(tmp_path: Path, watcher: Path) -> None:
    request_id = f"timeout-request-{uuid.uuid4().hex}"
    sentinel = tmp_path / "sentinel.txt"
    sentinel.write_text("unchanged", encoding="utf-8")
    legacy = Path("/tmp") / f"{request_id}.log"
    legacy.symlink_to(sentinel)
    try:
        result, _, temp_lines = _run_lifecycle(
            tmp_path,
            watcher=watcher,
            request_id=request_id,
            deploy_result=42,
        )
        created = _created_path(temp_lines)

        assert result.returncode == 0, result.stderr
        assert sentinel.read_text(encoding="utf-8") == "unchanged"
        assert legacy.is_symlink()
        assert created != legacy
        assert not created.exists()
    finally:
        legacy.unlink(missing_ok=True)


@pytest.mark.parametrize("watcher", WATCHERS)
def test_private_output_ignores_unwritable_legacy_path(tmp_path: Path, watcher: Path) -> None:
    request_id = f"timeout-request-{uuid.uuid4().hex}"
    legacy = Path("/tmp") / f"{request_id}.log"
    legacy.write_text("immutable legacy evidence", encoding="utf-8")
    legacy.chmod(0o400)
    try:
        result, trace, temp_lines = _run_lifecycle(
            tmp_path,
            watcher=watcher,
            request_id=request_id,
            deploy_result=42,
        )

        assert result.returncode == 0, result.stderr
        assert legacy.read_text(encoding="utf-8") == "immutable legacy evidence"
        assert "failed|failed" in trace.read_text(encoding="utf-8")
        assert "removed" in trace.read_text(encoding="utf-8")
        assert not _created_path(temp_lines).exists()
    finally:
        legacy.chmod(0o600)
        legacy.unlink(missing_ok=True)


@pytest.mark.parametrize(
    ("deploy_result", "terminal"),
    ((0, "success|completed"), (42, "failed|failed"), (124, "timeout|timed_out")),
)
@pytest.mark.parametrize("watcher", WATCHERS)
def test_private_output_lifecycle_is_truthful_and_private(
    tmp_path: Path,
    watcher: Path,
    deploy_result: int,
    terminal: str,
) -> None:
    result, trace, temp_lines = _run_lifecycle(
        tmp_path,
        watcher=watcher,
        request_id="ordinary-request",
        deploy_result=deploy_result,
    )
    created = _created_path(temp_lines)

    assert result.returncode == 0, result.stderr
    assert terminal in trace.read_text(encoding="utf-8")
    assert "removed" in trace.read_text(encoding="utf-8")
    assert "mode=600" in temp_lines
    assert created.name.startswith("sharipovai-deploy.")
    assert created.name.endswith(".log")
    assert not created.exists()


@pytest.mark.parametrize("watcher", WATCHERS)
@pytest.mark.parametrize("request_id", ("../../something", "a/b", "spaces are data", "x" * 4096))
def test_request_id_never_controls_private_output_path(
    tmp_path: Path,
    watcher: Path,
    request_id: str,
) -> None:
    result, _, temp_lines = _run_lifecycle(
        tmp_path,
        watcher=watcher,
        request_id=request_id,
        deploy_result=42,
    )
    created = _created_path(temp_lines)

    assert result.returncode == 0, result.stderr
    assert created.parent == tmp_path / "private-tmp"
    assert created.name.startswith("sharipovai-deploy.")
    assert request_id not in created.name
    assert not created.exists()


def test_watcher_copies_share_private_output_security_contract() -> None:
    blocks = []
    for watcher in WATCHERS:
        source = watcher.read_text(encoding="utf-8")
        assert 'output_file="/tmp/${request_id}.log"' not in source
        assert 'mktemp "${tmp_root%/}/sharipovai-deploy.XXXXXXXXXX.log"' in source
        assert "umask 077" in source
        assert "stat -c '%a'" in source
        assert "trap 'rm -f -- \"$output_file\"' EXIT" in source
        assert "see $output_file" not in source
        blocks.append(source.split("run_deploy_request_with_private_output() (", 1)[1].split("\nprocess_request()", 1)[0])
    assert blocks[0] == blocks[1]


@pytest.mark.parametrize("watcher", WATCHERS)
def test_private_output_creation_failure_terminalizes_without_fetch(tmp_path: Path, watcher: Path) -> None:
    trace = tmp_path / "trace.log"
    request = {
        "request_id": "mktemp-failure",
        "action": "deploy_main",
        "actor_id": 1,
        "chat_id": 1,
        "created_at": int(__import__("time").time()),
    }
    script = r'''
set -Eeuo pipefail
export SHARIPOVAI_DEPLOY_WATCHER_LIBRARY=1
source "$1"
validate_owner_request() { return 0; }
fetch_main() { echo fetched >> "$TRACE"; }
write_status() { printf '%s|%s\n' "$1" "$2" >> "$TRACE"; }
remove_request() { echo removed >> "$TRACE"; }
notify() { :; }
process_request "$REQUEST"
'''
    result = subprocess.run(
        ["bash", "-c", script, "watcher", str(watcher)],
        env=os.environ
        | {
            "REQUEST": json.dumps(request),
            "TMPDIR": str(tmp_path / "missing-private-tmp"),
            "TRACE": str(trace),
        },
        text=True,
        capture_output=True,
        check=False,
    )

    evidence = trace.read_text(encoding="utf-8")
    assert result.returncode == 0, result.stderr
    assert "failed|failed" in evidence
    assert "removed" in evidence
    assert "fetched" not in evidence


def test_installed_watcher_source_and_installer_keep_heredoc_stdin() -> None:
    for path in (Path("scripts/sharipovai_deploy_watcher.sh"),):
        source = path.read_text(encoding="utf-8")
        assert 'docker exec -i "$SERVICE" python - <<\'PY\'' in source, path
        assert 'docker exec -i \\\n    -e DEPLOY_STATE="$state"' in source, path
        assert 'docker exec "$SERVICE" python - <<\'PY\'' not in source, path
        assert 'docker exec \\\n    -e DEPLOY_STATE="$state"' not in source, path

    installer = Path("scripts/install_telegram_deploy_watcher.sh").read_text(encoding="utf-8")
    assert 'WATCHER_SOURCE="$ROOT/scripts/sharipovai_deploy_watcher.sh"' in installer
