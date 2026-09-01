#!/usr/bin/env bash
set -Eeuo pipefail

REPO_DIR="${SHARIPOVAI_REPO_DIR:-/opt/sharipovai-repo}"
COMPOSE_DIR="$REPO_DIR/deploy/vps"

if [ "$(id -u)" -ne 0 ]; then
    echo "Run this installer as root." >&2
    exit 1
fi

for path in \
    "$REPO_DIR/tools/self_healing_agent.py" \
    "$COMPOSE_DIR/self-healing-run.sh" \
    "$COMPOSE_DIR/prune_disposable_disk.sh" \
    "$COMPOSE_DIR/systemd/sharipovai-self-healing.service" \
    "$COMPOSE_DIR/systemd/sharipovai-self-healing.timer" \
    "$COMPOSE_DIR/docker-compose.yml" \
    "$COMPOSE_DIR/.env.vps"
do
    test -e "$path" || {
        echo "Required file is missing: $path" >&2
        exit 1
    }
done

# Only Git-tracked source code is made readable by the unprivileged
# in-container agent. Untracked .env files, databases and backups are untouched.
chmod a+rx "$REPO_DIR"
while IFS= read -r -d '' relative; do
    path="$REPO_DIR/$relative"
    if [ ! -L "$path" ]; then
        chmod a+r "$path"
    fi

    parent="$(dirname "$relative")"
    while [ "$parent" != "." ] && [ "$parent" != "/" ]; do
        chmod a+rx "$REPO_DIR/$parent"
        parent="$(dirname "$parent")"
    done
done < <(git -C "$REPO_DIR" ls-files -z)

python_check_image="$(
    docker compose \
        --env-file "$COMPOSE_DIR/.env.vps" \
        -f "$COMPOSE_DIR/docker-compose.yml" \
        --project-directory "$COMPOSE_DIR" \
        config --images |
    awk 'NR==1 {print; exit}'
)"
test -n "$python_check_image"

install -m 0750 \
    "$COMPOSE_DIR/self-healing-run.sh" \
    /usr/local/sbin/sharipovai-self-healing-run
install -m 0644 \
    "$COMPOSE_DIR/systemd/sharipovai-self-healing.service" \
    /etc/systemd/system/sharipovai-self-healing.service
install -m 0644 \
    "$COMPOSE_DIR/systemd/sharipovai-self-healing.timer" \
    /etc/systemd/system/sharipovai-self-healing.timer

cd "$COMPOSE_DIR"

# Recreate the application container so the read-only /workspace bind mount
# required by the in-container agent becomes active.
docker compose \
    --env-file .env.vps \
    -f docker-compose.yml \
    --project-directory "$COMPOSE_DIR" \
    up -d --force-recreate sharipovai caddy

for _ in $(seq 1 60); do
    state="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' sharipovai 2>/dev/null || echo missing)"
    if [ "$state" = "healthy" ] && curl -fsS --max-time 5 http://127.0.0.1:8000/health >/dev/null; then
        break
    fi
    sleep 3
done

test "$(docker inspect -f '{{.State.Running}}' sharipovai)" = "true"
test "$(docker inspect -f '{{.State.Running}}' sharipovai-caddy)" = "true"
test "$(docker inspect -f '{{.State.Health.Status}}' sharipovai)" = "healthy"

systemctl daemon-reload
systemctl enable --now sharipovai-self-healing.timer
systemctl start sharipovai-self-healing.service

echo "SELF_HEALING_INSTALLED"
systemctl --no-pager --full status sharipovai-self-healing.timer || true
