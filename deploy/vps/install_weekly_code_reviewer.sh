#!/usr/bin/env bash
set -Eeuo pipefail

REPO_DIR="${SHARIPOVAI_REPO_DIR:-/opt/sharipovai-repo}"
COMPOSE_DIR="$REPO_DIR/deploy/vps"

if [ "$(id -u)" -ne 0 ]; then
    echo "Run this installer as root." >&2
    exit 1
fi

for path in \
    "$REPO_DIR/tools/weekly_code_reviewer.py" \
    "$COMPOSE_DIR/weekly-code-review-run.sh" \
    "$COMPOSE_DIR/systemd/sharipovai-weekly-code-review.service" \
    "$COMPOSE_DIR/systemd/sharipovai-weekly-code-review.timer"
do
    test -e "$path" || {
        echo "Required file is missing: $path" >&2
        exit 1
    }
done

install -m 0750 \
    "$COMPOSE_DIR/weekly-code-review-run.sh" \
    /usr/local/sbin/sharipovai-weekly-code-review-run
install -m 0644 \
    "$COMPOSE_DIR/systemd/sharipovai-weekly-code-review.service" \
    /etc/systemd/system/sharipovai-weekly-code-review.service
install -m 0644 \
    "$COMPOSE_DIR/systemd/sharipovai-weekly-code-review.timer" \
    /etc/systemd/system/sharipovai-weekly-code-review.timer

systemctl daemon-reload
systemctl enable --now sharipovai-weekly-code-review.timer

echo "WEEKLY_CODE_REVIEWER_INSTALLED"
systemctl --no-pager --full status sharipovai-weekly-code-review.timer || true
systemctl list-timers --all --no-pager sharipovai-weekly-code-review.timer || true
