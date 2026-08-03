#!/usr/bin/env bash
set -Eeuo pipefail

REPO_DIR="${SHARIPOVAI_REPO_DIR:-/opt/sharipovai-repo}"
COMPOSE_DIR="$REPO_DIR/deploy/vps"
LOCK_FILE="/run/sharipovai-weekly-code-review.lock"

exec 9>"$LOCK_FILE"
if ! flock -n 9; then
    echo "WEEKLY_CODE_REVIEW_ALREADY_RUNNING"
    exit 0
fi

for path in \
    "$REPO_DIR/tools/weekly_code_reviewer.py" \
    "$COMPOSE_DIR/docker-compose.yml" \
    "$COMPOSE_DIR/.env.vps"
do
    test -e "$path" || {
        echo "Required file is missing: $path" >&2
        exit 1
    }
done

if [ "$(docker inspect -f '{{.State.Running}}' sharipovai 2>/dev/null || echo false)" != "true" ]; then
    echo "SharipovAI container is not running" >&2
    exit 1
fi

# The repository is mounted read-only at /workspace. Results and proposals are
# written only to the persistent data volume. No patch is ever applied here.
docker exec \
    --user 10001:10001 \
    -e PYTHONPATH=/workspace \
    -e WEEKLY_CODE_REVIEW_REPO_DIR=/workspace \
    -e WEEKLY_CODE_REVIEW_FIXES_DIR=/var/lib/sharipovai/agent_fixes \
    sharipovai \
    python /workspace/tools/weekly_code_reviewer.py
