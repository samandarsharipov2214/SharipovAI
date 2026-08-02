#!/usr/bin/env bash
# Host-side supervisor for the in-container SharipovAI Self-Healing Agent.
#
# The host needs only Docker, Docker Compose, Git, curl and standard shell tools.
# Python executes exclusively inside the sharipovai image.
set -u
set -o pipefail

REPO_DIR="${SHARIPOVAI_REPO_DIR:-/opt/sharipovai-repo}"
COMPOSE_DIR="$REPO_DIR/deploy/vps"
COMPOSE_FILE="$COMPOSE_DIR/docker-compose.yml"
ENV_FILE="$COMPOSE_DIR/.env.vps"
LOCK_FILE="/run/sharipovai-self-healing.lock"
HOST_LOG="/var/log/sharipovai-self-healing-host.log"
AGENT_PATH="/workspace/tools/self_healing_agent.py"
RUNTIME_DIR="/var/lib/sharipovai/.self_healing"

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

    # Do not require the HTTP health check here. An unhealthy but running
    # application container is exactly the state the Python agent must inspect.
    deadline=$((SECONDS + ${SELF_HEALING_CONTAINER_START_TIMEOUT_SECONDS:-90}))
    while [ "$SECONDS" -lt "$deadline" ]; do
        if container_running sharipovai; then
            return 0
        fi
        sleep 3
    done
    return 1
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

    docker exec --user 0 sharipovai sh -ec \
        "install -d -m 0700 '$RUNTIME_DIR'; : > '$RUNTIME_DIR/container_status.json'" \
        >/dev/null

    cat <<JSON | docker exec -i --user 0 sharipovai sh -ec \
        "cat > '$RUNTIME_DIR/container_status.json'; chmod 0600 '$RUNTIME_DIR/container_status.json'"
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
        docker exec -i --user 0 sharipovai sh -ec \
            "cat > '$RUNTIME_DIR/docker_logs_15m.log'; chmod 0600 '$RUNTIME_DIR/docker_logs_15m.log'"
}

run_agent() {
    docker exec \
        --user 0 \
        -e SELF_HEALING_REPO_DIR=/workspace \
        -e SELF_HEALING_BACKUP_PATH=/workspace/deploy/vps/backups/latest.tar.gz \
        -e SELF_HEALING_DATABASE_PATH=/var/lib/sharipovai/sharipovai_shared.db \
        -e SELF_HEALING_STDERR=0 \
        sharipovai \
        python "$AGENT_PATH"
}

read_agent_file() {
    docker exec --user 0 sharipovai sh -ec \
        "test -f '$1' && cat '$1' || true" 2>/dev/null
}

clear_agent_action() {
    if container_running sharipovai; then
        docker exec --user 0 sharipovai sh -ec \
            "rm -f '$RUNTIME_DIR/action' '$RUNTIME_DIR/action.json' '$RUNTIME_DIR/expected_sha'" \
            >/dev/null 2>&1 || true
    else
        compose run --rm --no-deps --user 0 --entrypoint sh sharipovai -ec \
            "rm -f '$RUNTIME_DIR/action' '$RUNTIME_DIR/action.json' '$RUNTIME_DIR/expected_sha'" \
            >/dev/null 2>&1 || true
    fi
}

restore_database() {
    local timestamp
    timestamp="$(date -u '+%Y%m%dT%H%M%SZ')"
    log "Stopping sharipovai for verified SQLite restore."
    compose stop sharipovai || return 1

    if ! compose run --rm --no-deps --user 0 --entrypoint sh sharipovai -ec "
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
        chown 10001:10001 \"\$db.new\"
        chmod 0600 \"\$db.new\"
        mv \"\$db.new\" \"\$db\"
        rm -f \"\$candidate\"
    "; then
        log "Database restore command failed; attempting to start the original stack."
        compose up -d sharipovai caddy || true
        return 1
    fi

    compose up -d sharipovai caddy || return 1
    wait_for_health
}

revert_automatic_commit() {
    local expected_sha="$1"
    local current_sha subject status

    if ! [[ "$expected_sha" =~ ^[0-9a-f]{40}$ ]]; then
        log "Refusing git revert: expected SHA is invalid: $expected_sha"
        return 1
    fi

    cd "$REPO_DIR" || return 1
    current_sha="$(git rev-parse HEAD 2>/dev/null || true)"
    subject="$(git log -1 --pretty=%s 2>/dev/null || true)"
    status="$(git status --porcelain --untracked-files=no 2>/dev/null || true)"

    if [ "$current_sha" != "$expected_sha" ]; then
        log "Refusing git revert: HEAD changed (expected=$expected_sha actual=$current_sha)."
        return 1
    fi
    case "$subject" in
        "[self-healing]"*) ;;
        *)
            log "Refusing git revert: commit is not marked [self-healing]: $subject"
            return 1
            ;;
    esac
    if [ -n "$status" ]; then
        log "Refusing git revert: tracked worktree is not clean."
        return 1
    fi

    git revert --no-edit "$expected_sha" || return 1
    log "Automatic commit reverted: $expected_sha"
    compose build sharipovai || return 1
    compose up -d sharipovai caddy || return 1
    wait_for_health
}

execute_action() {
    local action="$1" expected_sha="$2"
    case "$action" in
        ""|none)
            return 0
            ;;
        compose_up)
            log "Executing allow-listed action: compose_up"
            compose up -d && wait_for_health
            ;;
        restart_sharipovai)
            log "Executing allow-listed action: restart_sharipovai"
            compose restart sharipovai &&
                compose up -d caddy &&
                wait_for_health
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
        *)
            log "Refusing unknown self-healing action: $action"
            return 1
            ;;
    esac
}

main() {
    local agent_code=0 action=none expected_sha="" action_ok=0

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

    if ! ensure_stack; then
        log "Unable to bring SharipovAI stack to a running state."
        exit 1
    fi

    if ! write_runtime_input; then
        log "Unable to provide runtime input to the in-container agent."
        exit 1
    fi

    run_agent || agent_code=$?
    action="$(read_agent_file "$RUNTIME_DIR/action" | tr -d '\r\n[:space:]')"
    expected_sha="$(read_agent_file "$RUNTIME_DIR/expected_sha" | tr -d '\r\n[:space:]')"

    log "Agent finished: code=$agent_code action=${action:-none}"

    if execute_action "${action:-none}" "$expected_sha"; then
        action_ok=1
        clear_agent_action
    else
        log "Self-healing action failed and was left pending for inspection."
    fi

    if [ "$action_ok" -eq 1 ] && [ "${action:-none}" != "none" ] && container_running sharipovai; then
        write_runtime_input || true
        docker exec \
            --user 0 \
            -e SELF_HEALING_REPO_DIR=/workspace \
            -e SELF_HEALING_BACKUP_PATH=/workspace/deploy/vps/backups/latest.tar.gz \
            -e SELF_HEALING_DATABASE_PATH=/var/lib/sharipovai/sharipovai_shared.db \
            sharipovai \
            python "$AGENT_PATH" --verify-only \
            >/dev/null 2>&1 || true
    fi

    # The systemd unit remains successful if the agent reported an issue but
    # the wrapper completed its bounded workflow. Detailed state is in logs.
    exit 0
}

main "$@"
