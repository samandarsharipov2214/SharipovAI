import json
import os
import subprocess
from pathlib import Path


WATCHER = Path("deploy/vps/sharipovai-deploy-watcher")


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
    assert validation < source.index('  if ! fetch_main', validation)


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


def test_watcher_records_terminal_timeout_and_removes_request(tmp_path: Path) -> None:
    trace = tmp_path / "trace.log"
    request = {
        "request_id": "timeout-request",
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
fetch_main() { :; }
git() { echo 96296887; }
write_status() { printf '%s|%s\n' "$1" "$2" >> "$TRACE"; }
remove_request() { echo removed >> "$TRACE"; }
notify() { :; }
run_deploy_with_watchdog() { return 124; }
process_request "$REQUEST"
'''
    result = subprocess.run(
        ["bash", "-c", script, "watcher", str(WATCHER)],
        env=os.environ | {"TRACE": str(trace), "REQUEST": json.dumps(request)},
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "timeout|timed_out" in trace.read_text(encoding="utf-8")
    assert "removed" in trace.read_text(encoding="utf-8")


def test_installed_watcher_source_and_installer_keep_heredoc_stdin() -> None:
    for path in (Path("scripts/sharipovai_deploy_watcher.sh"),):
        source = path.read_text(encoding="utf-8")
        assert 'docker exec -i "$SERVICE" python - <<\'PY\'' in source, path
        assert 'docker exec -i \\\n    -e DEPLOY_STATE="$state"' in source, path
        assert 'docker exec "$SERVICE" python - <<\'PY\'' not in source, path
        assert 'docker exec \\\n    -e DEPLOY_STATE="$state"' not in source, path

    installer = Path("scripts/install_telegram_deploy_watcher.sh").read_text(encoding="utf-8")
    assert 'WATCHER_SOURCE="$ROOT/scripts/sharipovai_deploy_watcher.sh"' in installer
