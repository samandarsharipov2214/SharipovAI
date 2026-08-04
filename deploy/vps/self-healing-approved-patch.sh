#!/usr/bin/env bash
# Bounded implementation for the host-side apply_approved_patch action.
# This file is sourced by deploy/vps/self-healing-run.sh after its Docker,
# compose, logging, health and exact-revert helpers have been defined.

APPROVED_MANIFEST_PATH="${SELF_HEALING_APPROVED_MANIFEST_PATH:-$RUNTIME_DIR/approved_patch.json}"
PATCH_VERIFY_IMAGE="${SELF_HEALING_PATCH_VERIFY_IMAGE:-sharipovai:local}"
PATCH_MAX_BYTES="${SELF_HEALING_PATCH_MAX_BYTES:-2097152}"
PATCH_TEST_TIMEOUT_SECONDS="${SELF_HEALING_PATCH_TEST_TIMEOUT_SECONDS:-900}"
PATCH_REGRESSION_TIMEOUT_SECONDS="${SELF_HEALING_PATCH_REGRESSION_TIMEOUT_SECONDS:-1800}"
AGENT_DECISIONS_ENDPOINT="${SELF_HEALING_AGENT_DECISIONS_ENDPOINT:-http://127.0.0.1:8000/internal/agent-decisions}"

record_agent_decision() {
    local decision_id="$1" status="$2" phase="$3" message="$4"
    local base_sha="$5" patch_sha256="$6" commit_sha="${7:-}" health_verified="${8:-false}"

    if ! container_running sharipovai; then
        log "Cannot record agent_decisions result while sharipovai is stopped."
        return 1
    fi
    case "$AGENT_DECISIONS_ENDPOINT" in
        http://127.0.0.1:*/*|http://localhost:*/*) ;;
        *)
            log "Refusing non-loopback agent_decisions endpoint: $AGENT_DECISIONS_ENDPOINT"
            return 1
            ;;
    esac

    docker exec -i --user 0 \
        -e SELF_HEALING_DECISION_ID="$decision_id" \
        -e SELF_HEALING_RESULT_STATUS="$status" \
        -e SELF_HEALING_RESULT_PHASE="$phase" \
        -e SELF_HEALING_RESULT_MESSAGE="${message:0:3900}" \
        -e SELF_HEALING_RESULT_BASE_SHA="$base_sha" \
        -e SELF_HEALING_RESULT_PATCH_SHA256="$patch_sha256" \
        -e SELF_HEALING_RESULT_COMMIT_SHA="$commit_sha" \
        -e SELF_HEALING_RESULT_HEALTH="$health_verified" \
        -e SELF_HEALING_AGENT_DECISIONS_ENDPOINT="$AGENT_DECISIONS_ENDPOINT" \
        sharipovai python - <<'PY_AGENT_DECISION'
import json
import os
from urllib import request

payload = {
    "decision_id": os.environ["SELF_HEALING_DECISION_ID"],
    "action": "apply_approved_patch",
    "status": os.environ["SELF_HEALING_RESULT_STATUS"],
    "phase": os.environ["SELF_HEALING_RESULT_PHASE"],
    "message": os.environ["SELF_HEALING_RESULT_MESSAGE"],
    "base_sha": os.environ["SELF_HEALING_RESULT_BASE_SHA"],
    "patch_sha256": os.environ["SELF_HEALING_RESULT_PATCH_SHA256"],
    "commit_sha": os.environ.get("SELF_HEALING_RESULT_COMMIT_SHA", ""),
    "health_verified": os.environ.get("SELF_HEALING_RESULT_HEALTH", "false").lower() == "true",
}
token = os.environ.get("SHARIPOVAI_SERVICE_TOKEN", "").strip()
if not token:
    raise SystemExit("SHARIPOVAI_SERVICE_TOKEN is not configured")
endpoint = os.environ["SELF_HEALING_AGENT_DECISIONS_ENDPOINT"]
req = request.Request(
    endpoint,
    data=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
    headers={
        "Content-Type": "application/json",
        "X-SharipovAI-Service-Token": token,
    },
    method="POST",
)
with request.urlopen(req, timeout=10) as response:
    if response.status != 200:
        raise SystemExit(f"agent_decisions API returned HTTP {response.status}")
    result = json.loads(response.read().decode("utf-8"))
if result.get("status") != "ok":
    raise SystemExit(f"agent_decisions API rejected result: {result!r}")
PY_AGENT_DECISION
}

worktree_clean_at() {
    local expected_sha="$1"
    [ "$(git -C "$REPO_DIR" rev-parse HEAD 2>/dev/null || true)" = "$expected_sha" ] &&
        [ -z "$(git -C "$REPO_DIR" status --porcelain 2>/dev/null || true)" ]
}

cleanup_approved_patch_artifacts() {
    local patch_container_path="$1"
    if container_running sharipovai; then
        docker exec --user 0 sharipovai sh -ec \
            "rm -f '$APPROVED_MANIFEST_PATH' '$patch_container_path'" \
            >/dev/null 2>&1 || return 1
    fi
}

finalize_precommit_result() {
    local patch_container_path="$1" decision_id="$2" status="$3" phase="$4"
    local message="$5" base_sha="$6" patch_sha256="$7"
    record_agent_decision "$decision_id" "$status" "$phase" "$message" \
        "$base_sha" "$patch_sha256" || return 1
    cleanup_approved_patch_artifacts "$patch_container_path" || return 1
}

rollback_uncommitted_patch() {
    local patch_file="$1" base_sha="$2"
    cd "$REPO_DIR" || return 1
    if ! git diff --quiet || ! git diff --cached --quiet ||
        [ -n "$(git ls-files --others --exclude-standard)" ]; then
        git apply -R --index --whitespace=nowarn "$patch_file" || return 1
    fi
    worktree_clean_at "$base_sha"
}

discover_targeted_tests() {
    docker run --rm -i \
        -v "$REPO_DIR:/workspace:ro" \
        "$PATCH_VERIFY_IMAGE" \
        python - "$@" <<'PY_DISCOVER_TESTS'
from pathlib import Path
import sys
from tools.self_healing_agent import discover_related_tests

changed = {item for item in sys.argv[1:] if item}
selected = discover_related_tests(Path("/workspace"), changed, max_tests=25)
for path in selected:
    print(path)
PY_DISCOVER_TESTS
}

run_patch_tests() {
    local timeout_seconds="$1"
    shift
    timeout --signal=TERM --kill-after=30 "${timeout_seconds}s" \
        docker run --rm \
        -e PYTHONDONTWRITEBYTECODE=1 \
        -e PYTHONUNBUFFERED=1 \
        -e SHARIPOVAI_DATABASE_REQUIRED=0 \
        -e SHARIPOVAI_DISABLE_AUTH=1 \
        -e EXECUTION_KILL_SWITCH=1 \
        -e TESTNET_EXECUTION_ENABLED=0 \
        -e EXCHANGE_LIVE_TRADING_ENABLED=0 \
        -v "$REPO_DIR:/workspace:ro" \
        -w /workspace \
        "$PATCH_VERIFY_IMAGE" \
        python -m pytest -q --disable-warnings -p no:cacheprovider "$@"
}

apply_approved_patch() {
    local patch_dir manifest_output decision_id base_sha patch_sha256 patch_container_path
    local current_sha actual_sha patch_bytes phase message commit_sha=""
    local -a changed_paths targeted_tests regression_paths

    if ! [[ "$PATCH_MAX_BYTES" =~ ^[0-9]+$ ]] || [ "$PATCH_MAX_BYTES" -lt 1 ] ||
        ! [[ "$PATCH_TEST_TIMEOUT_SECONDS" =~ ^[0-9]+$ ]] || [ "$PATCH_TEST_TIMEOUT_SECONDS" -lt 1 ] ||
        ! [[ "$PATCH_REGRESSION_TIMEOUT_SECONDS" =~ ^[0-9]+$ ]] || [ "$PATCH_REGRESSION_TIMEOUT_SECONDS" -lt 1 ]; then
        log "Approved patch numeric limits are invalid."
        return 1
    fi
    if ! [[ "$APPROVED_MANIFEST_PATH" =~ ^/var/lib/sharipovai/\.self_healing/[A-Za-z0-9._/-]+$ ]] ||
        [[ "$APPROVED_MANIFEST_PATH" == *"//"* ]] || [[ "$APPROVED_MANIFEST_PATH" == *"/../"* ]]; then
        log "Approved manifest path is outside the self-healing runtime directory."
        return 1
    fi

    patch_dir="$(mktemp -d /var/tmp/sharipovai-approved-patch.XXXXXX)" || return 1
    chmod 0700 "$patch_dir"

    if ! docker cp "sharipovai:$APPROVED_MANIFEST_PATH" "$patch_dir/approved.json" >/dev/null 2>&1; then
        log "Approved patch manifest is missing: $APPROVED_MANIFEST_PATH"
        rm -rf "$patch_dir"
        return 1
    fi

    if ! manifest_output="$(docker run --rm -i \
        -v "$patch_dir:/patches:ro" \
        "$PATCH_VERIFY_IMAGE" python - <<'PY_MANIFEST'
import json
import re
from pathlib import PurePosixPath

with open("/patches/approved.json", "r", encoding="utf-8") as handle:
    payload = json.load(handle)
required = {"decision_id", "base_sha", "patch_sha256", "patch_container_path"}
if not isinstance(payload, dict) or set(payload) != required:
    raise SystemExit("approved manifest must contain exactly the required fields")
decision_id = str(payload["decision_id"])
base_sha = str(payload["base_sha"]).lower()
patch_sha = str(payload["patch_sha256"]).lower()
container_path = str(payload["patch_container_path"])
if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,169}", decision_id):
    raise SystemExit("invalid decision_id")
if not re.fullmatch(r"[0-9a-f]{40}", base_sha):
    raise SystemExit("invalid base_sha")
if not re.fullmatch(r"[0-9a-f]{64}", patch_sha):
    raise SystemExit("invalid patch_sha256")
if not re.fullmatch(r"/var/lib/sharipovai/\.self_healing/[A-Za-z0-9._/-]+", container_path):
    raise SystemExit("patch_container_path is outside the approved runtime directory")
path = PurePosixPath(container_path)
if any(part in {"", ".", ".."} for part in path.parts) or path.as_posix() != container_path:
    raise SystemExit("patch_container_path is not normalized")
print("\t".join((decision_id, base_sha, patch_sha, container_path)))
PY_MANIFEST
    )"; then
        log "Approved patch manifest validation failed."
        rm -rf "$patch_dir"
        return 1
    fi

    IFS=$'\t' read -r decision_id base_sha patch_sha256 patch_container_path <<<"$manifest_output"
    if [ -z "$decision_id" ] || [ -z "$patch_container_path" ]; then
        log "Approved patch manifest produced incomplete values."
        rm -rf "$patch_dir"
        return 1
    fi

    if ! docker exec --user 0 sharipovai sh -ec \
        "test -f '$patch_container_path' && test ! -L '$patch_container_path' && test -s '$patch_container_path'"; then
        message="approved patch is missing, empty, or a symlink"
        finalize_precommit_result "$patch_container_path" "$decision_id" rejected patch_read "$message" "$base_sha" "$patch_sha256" || { rm -rf "$patch_dir"; return 1; }
        rm -rf "$patch_dir"
        return 0
    fi
    if ! docker cp "sharipovai:$patch_container_path" "$patch_dir/candidate.patch" >/dev/null 2>&1; then
        log "Unable to copy approved patch from the container."
        rm -rf "$patch_dir"
        return 1
    fi
    chmod 0400 "$patch_dir/approved.json" "$patch_dir/candidate.patch"

    patch_bytes="$(wc -c <"$patch_dir/candidate.patch" | tr -d '[:space:]')"
    if ! [[ "$patch_bytes" =~ ^[0-9]+$ ]] || [ "$patch_bytes" -lt 1 ] || [ "$patch_bytes" -gt "$PATCH_MAX_BYTES" ]; then
        message="approved patch size is outside 1..$PATCH_MAX_BYTES bytes"
        finalize_precommit_result "$patch_container_path" "$decision_id" rejected patch_size "$message" "$base_sha" "$patch_sha256" || { rm -rf "$patch_dir"; return 1; }
        rm -rf "$patch_dir"
        return 0
    fi

    actual_sha="$(sha256sum "$patch_dir/candidate.patch" | awk '{print $1}')"
    if [ "$actual_sha" != "$patch_sha256" ]; then
        message="approved patch SHA-256 mismatch"
        finalize_precommit_result "$patch_container_path" "$decision_id" rejected patch_hash "$message" "$base_sha" "$patch_sha256" || { rm -rf "$patch_dir"; return 1; }
        rm -rf "$patch_dir"
        return 0
    fi

    cd "$REPO_DIR" || { rm -rf "$patch_dir"; return 1; }
    current_sha="$(git rev-parse HEAD 2>/dev/null || true)"
    if [ "$current_sha" != "$base_sha" ]; then
        message="repository HEAD does not match approved base_sha"
        finalize_precommit_result "$patch_container_path" "$decision_id" rejected base_sha "$message" "$base_sha" "$patch_sha256" || { rm -rf "$patch_dir"; return 1; }
        rm -rf "$patch_dir"
        return 0
    fi
    if [ -n "$(git status --porcelain 2>/dev/null || true)" ]; then
        message="repository worktree is not clean"
        finalize_precommit_result "$patch_container_path" "$decision_id" rejected worktree "$message" "$base_sha" "$patch_sha256" || { rm -rf "$patch_dir"; return 1; }
        rm -rf "$patch_dir"
        return 0
    fi

    log "Re-verifying approved patch with Security Guard: decision_id=$decision_id"
    if ! docker run --rm \
        -v "$REPO_DIR:/workspace:ro" \
        -v "$patch_dir:/patches:ro" \
        "$PATCH_VERIFY_IMAGE" \
        python -m development_control.patch_policy --verify /patches/candidate.patch; then
        message="Security Guard rejected the approved patch"
        finalize_precommit_result "$patch_container_path" "$decision_id" rejected security_guard "$message" "$base_sha" "$patch_sha256" || { rm -rf "$patch_dir"; return 1; }
        rm -rf "$patch_dir"
        return 0
    fi

    if ! worktree_clean_at "$base_sha"; then
        log "Repository changed during patch verification; refusing apply."
        rm -rf "$patch_dir"
        return 1
    fi
    if ! git apply --check --whitespace=error "$patch_dir/candidate.patch"; then
        message="git apply --check failed"
        finalize_precommit_result "$patch_container_path" "$decision_id" rejected git_apply_check "$message" "$base_sha" "$patch_sha256" || { rm -rf "$patch_dir"; return 1; }
        rm -rf "$patch_dir"
        return 0
    fi
    if ! git apply --index --whitespace=error "$patch_dir/candidate.patch"; then
        message="git apply failed"
        if ! rollback_uncommitted_patch "$patch_dir/candidate.patch" "$base_sha"; then
            record_agent_decision "$decision_id" rollback_failed git_apply \
                "$message; pre-commit cleanup failed" "$base_sha" "$patch_sha256" || true
            rm -rf "$patch_dir"
            return 1
        fi
        finalize_precommit_result "$patch_container_path" "$decision_id" failed_precommit git_apply \
            "$message" "$base_sha" "$patch_sha256" || { rm -rf "$patch_dir"; return 1; }
        rm -rf "$patch_dir"
        return 0
    fi
    if git diff --cached --quiet || ! git diff --quiet ||
        [ -n "$(git ls-files --others --exclude-standard)" ]; then
        message="patch produced no staged changes or unexpected unstaged files"
        rollback_uncommitted_patch "$patch_dir/candidate.patch" "$base_sha" || return 1
        finalize_precommit_result "$patch_container_path" "$decision_id" failed_precommit staged_state "$message" "$base_sha" "$patch_sha256" || { rm -rf "$patch_dir"; return 1; }
        rm -rf "$patch_dir"
        return 0
    fi
    if git diff --cached --summary | grep -Eq 'mode change|create mode 160000'; then
        message="patch introduced a forbidden mode or submodule change"
        rollback_uncommitted_patch "$patch_dir/candidate.patch" "$base_sha" || return 1
        finalize_precommit_result "$patch_container_path" "$decision_id" rejected file_mode "$message" "$base_sha" "$patch_sha256" || { rm -rf "$patch_dir"; return 1; }
        rm -rf "$patch_dir"
        return 0
    fi

    mapfile -d '' changed_paths < <(git diff --cached --name-only -z)
    mapfile -t targeted_tests < <(discover_targeted_tests "${changed_paths[@]}")
    if [ "${#targeted_tests[@]}" -eq 0 ]; then
        targeted_tests=(tests)
    fi
    log "Running targeted tests for approved patch: ${targeted_tests[*]}"
    if ! run_patch_tests "$PATCH_TEST_TIMEOUT_SECONDS" --maxfail=1 "${targeted_tests[@]}"; then
        message="targeted tests failed"
        rollback_uncommitted_patch "$patch_dir/candidate.patch" "$base_sha" || return 1
        finalize_precommit_result "$patch_container_path" "$decision_id" failed_precommit targeted_tests "$message" "$base_sha" "$patch_sha256" || { rm -rf "$patch_dir"; return 1; }
        rm -rf "$patch_dir"
        return 0
    fi

    regression_paths=()
    for phase in tests agents/tests ai_core/tests confidence/tests config/tests consensus/tests dashboard/tests data_layer/tests decision/tests exchange_connector/tests learning/tests learning_engine/tests news_agent/tests news_monitor/tests paper_trading/tests portfolio_engine/tests risk_engine/tests runner/tests; do
        [ -d "$REPO_DIR/$phase" ] && regression_paths+=("$phase")
    done
    log "Running full regression tests for approved patch."
    if ! run_patch_tests "$PATCH_REGRESSION_TIMEOUT_SECONDS" "${regression_paths[@]}"; then
        message="regression tests failed"
        rollback_uncommitted_patch "$patch_dir/candidate.patch" "$base_sha" || return 1
        finalize_precommit_result "$patch_container_path" "$decision_id" failed_precommit regression_tests "$message" "$base_sha" "$patch_sha256" || { rm -rf "$patch_dir"; return 1; }
        rm -rf "$patch_dir"
        return 0
    fi

    if [ "$(git rev-parse HEAD)" != "$base_sha" ] || ! git diff --quiet ||
        [ -n "$(git ls-files --others --exclude-standard)" ]; then
        message="repository changed before commit"
        log "$message; rolling back approved patch."
        rollback_uncommitted_patch "$patch_dir/candidate.patch" "$base_sha" || return 1
        finalize_precommit_result "$patch_container_path" "$decision_id" failed_precommit precommit_race \
            "$message" "$base_sha" "$patch_sha256" || { rm -rf "$patch_dir"; return 1; }
        rm -rf "$patch_dir"
        return 0
    fi
    if ! git -c user.name='SharipovAI Self-Healing' \
        -c user.email='self-healing@localhost' \
        commit -m "[self-healing] fix $decision_id"; then
        message="git commit failed"
        rollback_uncommitted_patch "$patch_dir/candidate.patch" "$base_sha" || return 1
        finalize_precommit_result "$patch_container_path" "$decision_id" failed_precommit commit "$message" "$base_sha" "$patch_sha256" || { rm -rf "$patch_dir"; return 1; }
        rm -rf "$patch_dir"
        return 0
    fi
    commit_sha="$(git rev-parse HEAD)"
    log "Approved patch committed: decision_id=$decision_id commit=$commit_sha"

    phase=compose_build
    if ! compose build sharipovai; then
        message="docker compose build failed"
    elif ! compose up -d sharipovai caddy; then
        phase=compose_up
        message="docker compose up failed"
    elif ! wait_for_health; then
        phase=health
        message="health verification failed after approved patch deployment"
    else
        if ! cleanup_approved_patch_artifacts "$patch_container_path"; then
            phase=artifact_cleanup
            message="approved patch artifact cleanup failed"
        elif record_agent_decision "$decision_id" applied complete \
            "approved patch applied and health verified" "$base_sha" "$patch_sha256" "$commit_sha" true; then
            rm -rf "$patch_dir"
            log "Approved patch completed successfully: decision_id=$decision_id commit=$commit_sha"
            return 0
        else
            phase=agent_decisions
            message="agent_decisions result persistence failed"
        fi
    fi

    log "$message; reverting exact automatic commit $commit_sha"
    if ! revert_automatic_commit "$commit_sha"; then
        record_agent_decision "$decision_id" rollback_failed "$phase" \
            "$message; exact git revert failed" "$base_sha" "$patch_sha256" "$commit_sha" false || true
        rm -rf "$patch_dir"
        return 1
    fi
    if ! record_agent_decision "$decision_id" reverted "$phase" \
        "$message; exact automatic commit reverted" "$base_sha" "$patch_sha256" "$commit_sha" true; then
        rm -rf "$patch_dir"
        return 1
    fi
    if ! cleanup_approved_patch_artifacts "$patch_container_path"; then
        rm -rf "$patch_dir"
        return 1
    fi
    rm -rf "$patch_dir"
    return 0
}
