#!/usr/bin/env bash
# Host-side supervisor for the bounded SharipovAI Self-Healing Agent.
set -u
set -o pipefail

REPO_DIR="${SHARIPOVAI_REPO_DIR:-/opt/sharipovai-repo}"
COMPOSE_DIR="$REPO_DIR/deploy/vps"
COMPOSE_FILE="$COMPOSE_DIR/docker-compose.yml"
ENV_FILE="$COMPOSE_DIR/.env.vps"
LOCK_FILE="/run/sharipovai-self-healing.lock"
HOST_LOG="/var/log/sharipovai-self-healing-host.log"
AGENT_RUNNER_PATH="/workspace/tools/self_healing_runner.py"
AGENT_ACTION_PATH="/workspace/tools/self_healing_agent.py"
GIT_SNAPSHOT_HELPER="$REPO_DIR/tools/self_healing_git_snapshot.sh"
RUNTIME_DIR="/var/lib/sharipovai/.self_healing"
GIT_SNAPSHOT_DIR="$RUNTIME_DIR/git-metadata"
CONTAINER_USER="${SELF_HEALING_CONTAINER_USER:-10001:10001}"

mkdir -p "$(dirname "$HOST_LOG")"
touch "$HOST_LOG"
chmod 0600 "$HOST_LOG"

log() {
    local message
    message="$(date -u '+%Y-%m-%dT%H:%M:%SZ') $*"
    printf '%s\n' "$message" >>"$HOST_LOG"
    logger -t sharipovai-self-healing -- "$*" 2>/dev/null || true
}

compose() {
    docker compose \
        --env-file "$ENV_FILE" \
        -f "$COMPOSE_FILE" \
        --project-directory "$COMPOSE_DIR" \
        "$@"
}

container_exists() {
    docker inspect "$1" >/dev/null 2>&1
}

container_running() {
    [ "$(docker inspect -f '{{.State.Running}}' "$1" 2>/dev/null || echo false)" = "true" ]
}

container_health() {
    docker inspect \
        -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' \
        "$1" 2>/dev/null || echo missing
}

wait_for_health() {
    local deadline status
    deadline=$((SECONDS + ${SELF_HEALING_STARTUP_TIMEOUT_SECONDS:-180}))
    while [ "$SECONDS" -lt "$deadline" ]; do
        if container_running sharipovai; then
            status="$(container_health sharipovai)"
            if [ "$status" = "healthy" ] || [ "$status" = "none" ]; then
                if curl -fsS --max-time 5 http://127.0.0.1:8000/health >/dev/null 2>&1; then
                    return 0
                fi
            fi
        fi
        sleep 3
    done
    return 1
}

ensure_stack() {
    local recovery_needed=0 deadline
    container_running sharipovai || recovery_needed=1
    container_running sharipovai-caddy || recovery_needed=1
    if [ "$recovery_needed" -eq 1 ]; then
        log "Stack is incomplete; running docker compose up -d."
        compose up -d || return 1
    fi
    deadline=$((SECONDS + ${SELF_HEALING_CONTAINER_START_TIMEOUT_SECONDS:-90}))
    while [ "$SECONDS" -lt "$deadline" ]; do
        container_running sharipovai && return 0
        sleep 3
    done
    return 1
}

prepare_git_snapshot() {
    if [ ! -r "$GIT_SNAPSHOT_HELPER" ]; then
        log "Trusted Git snapshot helper is missing: $GIT_SNAPSHOT_HELPER"
        return 1
    fi
    if ! env \
        SHARIPOVAI_REPO_DIR="$REPO_DIR" \
        SELF_HEALING_CONTAINER_NAME=sharipovai \
        SELF_HEALING_CONTAINER_USER="$CONTAINER_USER" \
        SELF_HEALING_RUNTIME_DIR="$RUNTIME_DIR" \
        SELF_HEALING_WORK_TREE=/workspace \
        bash "$GIT_SNAPSHOT_HELPER" >/dev/null; then
        log "Unable to prepare trusted read-only Git metadata snapshot."
        return 1
    fi
    return 0
}

write_runtime_input() {
    local app_exists=false app_running=false app_health=missing
    local caddy_exists=false caddy_running=false caddy_health=missing
    local generated_at

    if container_exists sharipovai; then
        app_exists=true
        container_running sharipovai && app_running=true
        app_health="$(container_health sharipovai)"
    fi
    if container_exists sharipovai-caddy; then
        caddy_exists=true
        container_running sharipovai-caddy && caddy_running=true
        caddy_health="$(container_health sharipovai-caddy)"
    fi
    generated_at="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"

    docker exec --user "$CONTAINER_USER" sharipovai sh -ec \
        "install -d -m 0700 '$RUNTIME_DIR'; : > '$RUNTIME_DIR/container_status.json'" \
        >/dev/null || return 1

    cat <<JSON | docker exec -i --user "$CONTAINER_USER" sharipovai sh -ec \
        "cat > '$RUNTIME_DIR/container_status.json'; chmod 0600 '$RUNTIME_DIR/container_status.json'" || return 1
{
  "generated_at": "$generated_at",
  "containers": {
    "sharipovai": {
      "exists": $app_exists,
      "running": $app_running,
      "health": "$app_health"
    },
    "sharipovai-caddy": {
      "exists": $caddy_exists,
      "running": $caddy_running,
      "health": "$caddy_health"
    }
  }
}
JSON

    docker logs --since 15m sharipovai 2>&1 |
        tail -c "${SELF_HEALING_MAX_HOST_LOG_BYTES:-2097152}" |
        docker exec -i --user "$CONTAINER_USER" sharipovai sh -ec \
            "cat > '$RUNTIME_DIR/docker_logs_15m.log'; chmod 0600 '$RUNTIME_DIR/docker_logs_15m.log'"
}

run_agent() {
    docker exec \
        --user "$CONTAINER_USER" \
        -e SELF_HEALING_REPO_DIR=/workspace \
        -e SELF_HEALING_BACKUP_PATH=/workspace/deploy/vps/backups/latest.tar.gz \
        -e SELF_HEALING_DATABASE_PATH=/var/lib/sharipovai/sharipovai_shared.db \
        -e SELF_HEALING_STDERR=0 \
        -e GIT_DIR="$GIT_SNAPSHOT_DIR" \
        -e GIT_WORK_TREE=/workspace \
        -e GIT_OPTIONAL_LOCKS=0 \
        sharipovai python "$AGENT_RUNNER_PATH"
}

read_agent_file() {
    docker exec --user "$CONTAINER_USER" sharipovai sh -ec \
        "test -f '$1' && cat '$1' || true" 2>/dev/null
}

reject_stale_noncritical_authority() {
    local rejected
    if ! rejected="$(docker exec --user "$CONTAINER_USER" sharipovai \
        python "$AGENT_ACTION_PATH" --action-lifecycle reject-stale)"; then
        log "Unable to reject an abandoned non-critical action claim; failing closed."
        return 1
    fi
    if [ -n "$rejected" ]; then
        log "Rejected stale non-critical action generation without replay: $rejected"
    fi
}

claim_noncritical_action() {
    docker exec --user "$CONTAINER_USER" sharipovai \
        python "$AGENT_ACTION_PATH" --action-lifecycle claim
}

terminalize_noncritical_action() {
    local status="$1" generation="$2" detail="$3"
    docker exec --user "$CONTAINER_USER" sharipovai \
        python "$AGENT_ACTION_PATH" \
        --action-lifecycle terminalize \
        --action-generation "$generation" \
        --action-result "$status" \
        --action-detail "$detail"
}

clear_agent_action() {
    if container_running sharipovai; then
        docker exec --user "$CONTAINER_USER" sharipovai sh -ec \
            "rm -f '$RUNTIME_DIR/action' '$RUNTIME_DIR/action.json' '$RUNTIME_DIR/expected_sha' '$RUNTIME_DIR/critical_action_request.json'" \
            >/dev/null 2>&1 || true
    else
        compose run --rm --no-deps --user "$CONTAINER_USER" --entrypoint sh sharipovai -ec \
            "rm -f '$RUNTIME_DIR/action' '$RUNTIME_DIR/action.json' '$RUNTIME_DIR/expected_sha' '$RUNTIME_DIR/critical_action_request.json'" \
            >/dev/null 2>&1 || true
    fi
}

restore_database() {
    local timestamp
    timestamp="$(date -u '+%Y%m%dT%H%M%SZ')"
    log "Stopping sharipovai for verified SQLite restore."
    compose stop sharipovai || return 1

    if ! compose run --rm --no-deps --user "$CONTAINER_USER" --entrypoint sh sharipovai -ec "
        set -u
        db='/var/lib/sharipovai/sharipovai_shared.db'
        candidate='$RUNTIME_DIR/restore_candidate.db'
        test -s \"\$candidate\"
        python - <<'PY'
import sqlite3
path = '/var/lib/sharipovai/.self_healing/restore_candidate.db'
with sqlite3.connect(f'file:{path}?mode=ro', uri=True) as connection:
    result = connection.execute('PRAGMA integrity_check').fetchall()
if result != [('ok',)]:
    raise SystemExit(f'invalid restore candidate: {result!r}')
PY
        if [ -e \"\$db\" ]; then
            mv \"\$db\" \"\$db.corrupt.$timestamp\"
        fi
        rm -f \"\$db-wal\" \"\$db-shm\" \"\$db.new\"
        cp \"\$candidate\" \"\$db.new\"
        chmod 0600 \"\$db.new\"
        mv \"\$db.new\" \"\$db\"
        rm -f \"\$candidate\"
    "; then
        log "Database restore failed; attempting to restart the original stack."
        compose up -d sharipovai caddy || true
        return 1
    fi

    compose up -d sharipovai caddy || return 1
    wait_for_health
}

revert_automatic_commit() {
    local expected_sha="$1"
    local current_sha subject status
    [[ "$expected_sha" =~ ^[0-9a-f]{40}$ ]] || {
        log "Refusing git revert: invalid expected SHA: $expected_sha"
        return 1
    }
    cd "$REPO_DIR" || return 1
    current_sha="$(git rev-parse HEAD 2>/dev/null || true)"
    subject="$(git log -1 --pretty=%s 2>/dev/null || true)"
    status="$(git status --porcelain 2>/dev/null || true)"
    [ "$current_sha" = "$expected_sha" ] || {
        log "Refusing git revert: HEAD changed (expected=$expected_sha actual=$current_sha)."
        return 1
    }
    case "$subject" in
        "[self-healing]"*) ;;
        *) log "Refusing git revert: commit is not marked [self-healing]: $subject"; return 1 ;;
    esac
    [ -z "$status" ] || {
        log "Refusing git revert: worktree is not clean."
        return 1
    }
    git revert --no-edit "$expected_sha" || return 1
    log "Automatic commit reverted: $expected_sha"
    compose build sharipovai || return 1
    compose up -d sharipovai caddy || return 1
    wait_for_health
}

critical_action_is_owner_approved() {
    local action="$1"
    docker exec --user "$CONTAINER_USER" sharipovai python - "$action" <<'PY'
import json
import os
import sys
from pathlib import Path

from development_control.general_controller import DevelopmentChangeController

action = sys.argv[1]
meta_path = Path("/var/lib/sharipovai/.self_healing/action.json")
try:
    metadata = json.loads(meta_path.read_text(encoding="utf-8"))
    decision_id = str(metadata.get("approval_decision_id", "")).strip()
    DevelopmentChangeController().claim_critical_action(decision_id, action)
except Exception:
    raise SystemExit(1)
PY
}

PRUNE_DISPOSABLE_DISK_HELPER="$REPO_DIR/deploy/vps/prune_disposable_disk.sh"
APPROVED_PATCH_HELPER="$REPO_DIR/deploy/vps/self-healing-approved-patch.sh"
APPROVED_PATCH_CLAIM_HELPER="$REPO_DIR/deploy/vps/self-healing-approved-claim.sh"
if [ -r "$APPROVED_PATCH_HELPER" ] && [ -r "$APPROVED_PATCH_CLAIM_HELPER" ]; then
    # shellcheck source=deploy/vps/self-healing-approved-patch.sh
    . "$APPROVED_PATCH_HELPER"
    # shellcheck source=deploy/vps/self-healing-approved-claim.sh
    . "$APPROVED_PATCH_CLAIM_HELPER"
else
    claim_approved_patch() {
        log "Approved patch claim helper is missing: $APPROVED_PATCH_CLAIM_HELPER"
        return 1
    }
    apply_approved_patch() {
        log "Approved patch helper is missing: $APPROVED_PATCH_HELPER"
        return 1
    }
fi

run_prune_disposable_disk() {
    if [ ! -r "$PRUNE_DISPOSABLE_DISK_HELPER" ]; then
        log "Disposable disk prune helper is missing: $PRUNE_DISPOSABLE_DISK_HELPER"
        return 1
    fi
    SELF_HEALING_HOST_LOG="$HOST_LOG" \
    SHARIPOVAI_REPO_DIR="$REPO_DIR" \
    bash "$PRUNE_DISPOSABLE_DISK_HELPER"
}

execute_action() {
    local action="$1" expected_sha="$2"
    case "$action" in
        restore_database|git_revert)
            if ! critical_action_is_owner_approved "$action"; then
                log "Refusing critical self-healing action without explicit Telegram owner approval: $action"
                return 1
            fi
            ;;
    esac
    case "$action" in
        ""|none) return 0 ;;
        compose_up)
            log "Executing allow-listed action: compose_up"
            compose up -d && wait_for_health
            ;;
        restart_sharipovai)
            log "Executing allow-listed action: restart_sharipovai"
            compose restart sharipovai && compose up -d caddy && wait_for_health
            ;;
        restart_caddy)
            log "Executing allow-listed action: restart_caddy"
            compose restart caddy
            ;;
        restore_database)
            log "Executing allow-listed action: restore_database"
            restore_database
            ;;
        git_revert)
            log "Executing allow-listed action: git_revert"
            revert_automatic_commit "$expected_sha"
            ;;
        apply_approved_patch)
            log "Executing allow-listed action: apply_approved_patch"
            claim_approved_patch && apply_approved_patch
            ;;
        prune_disposable_disk)
            log "Executing allow-listed action: prune_disposable_disk"
            run_prune_disposable_disk
            ;;
        *)
            log "Refusing unknown self-healing action: $action"
            return 1
            ;;
    esac
}

main() {
    local agent_code=0 action=none expected_sha="" action_ok=0
    local claim_record="" claimed_action="" generation=""
    exec 9>"$LOCK_FILE"
    if ! flock -n 9; then
        log "Another self-healing run is active; skipping."
        exit 0
    fi
    cd "$COMPOSE_DIR" || {
        log "Compose directory is missing: $COMPOSE_DIR"
        exit 1
    }
    if [ ! -f "$ENV_FILE" ] || [ ! -f "$COMPOSE_FILE" ]; then
        log "Deployment files are missing."
        exit 1
    fi
    ensure_stack || {
        log "Unable to bring SharipovAI stack to a running state."
        exit 1
    }
    log "Running bounded disposable disk prune before the in-container agent."
    if run_prune_disposable_disk; then
        log "Bounded disposable disk prune finished."
    else
        log "Bounded disposable disk prune failed closed; continuing the self-healing cycle."
    fi
    prepare_git_snapshot || {
        log "Git verification remains fail-closed because the trusted snapshot is unavailable."
        exit 1
    }
    write_runtime_input || {
        log "Unable to provide runtime input to the in-container agent."
        exit 1
    }
    reject_stale_noncritical_authority || exit 1

    run_agent || agent_code=$?
    action="$(read_agent_file "$RUNTIME_DIR/action" | tr -d '\r\n[:space:]')"
    expected_sha="$(read_agent_file "$RUNTIME_DIR/expected_sha" | tr -d '\r\n[:space:]')"
    log "Agent finished: code=$agent_code action=${action:-none}"

    case "${action:-none}" in
        ""|none)
            action_ok=1
            ;;
        restore_database|git_revert|apply_approved_patch)
            # Critical DCC authorization and claim semantics are unchanged.
            if execute_action "$action" "$expected_sha"; then
                action_ok=1
                clear_agent_action
            else
                log "Critical self-healing action failed and remains governed by its DCC decision."
            fi
            ;;
        *)
            if ! claim_record="$(claim_noncritical_action)" || [ -z "$claim_record" ]; then
                log "Non-critical action could not be atomically claimed; execution refused."
            else
                IFS='|' read -r claimed_action generation expected_sha <<EOF
$claim_record
EOF
                if [ "$claimed_action" != "$action" ] || [ -z "$generation" ]; then
                    log "Claimed action metadata did not match the published action; execution refused."
                    terminalize_noncritical_action rejected "$generation" "claim metadata mismatch" || true
                elif execute_action "$claimed_action" "$expected_sha"; then
                    if terminalize_noncritical_action success "$generation" "allow-listed host action completed"; then
                        action_ok=1
                    else
                        log "Action succeeded but terminal evidence could not be persisted; claim remains non-replayable."
                    fi
                else
                    if terminalize_noncritical_action failed "$generation" "allow-listed host action returned failure"; then
                        log "Non-critical self-healing action failed and was terminalized: generation=$generation"
                    else
                        log "Action failed and terminal evidence could not be persisted; claim remains non-replayable."
                    fi
                fi
            fi
            ;;
    esac

    if [ "$action_ok" -eq 1 ] && [ "${action:-none}" != "none" ] && container_running sharipovai; then
        write_runtime_input || true
        if prepare_git_snapshot; then
            docker exec \
                --user "$CONTAINER_USER" \
                -e SELF_HEALING_REPO_DIR=/workspace \
                -e SELF_HEALING_BACKUP_PATH=/workspace/deploy/vps/backups/latest.tar.gz \
                -e SELF_HEALING_DATABASE_PATH=/var/lib/sharipovai/sharipovai_shared.db \
                -e GIT_DIR="$GIT_SNAPSHOT_DIR" \
                -e GIT_WORK_TREE=/workspace \
                -e GIT_OPTIONAL_LOCKS=0 \
                sharipovai python "$AGENT_RUNNER_PATH" --verify-only \
                >/dev/null 2>&1 || true
        else
            log "Post-action verification skipped because trusted Git snapshot refresh failed."
        fi
    fi
    exit 0
}

main "$@"
