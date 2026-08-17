#!/usr/bin/env bash
# Build a sanitized, container-readable Git metadata snapshot for Self-Healing.
set -euo pipefail

REPO_DIR="${SHARIPOVAI_REPO_DIR:-/opt/sharipovai-repo}"
CONTAINER_NAME="${SELF_HEALING_CONTAINER_NAME:-sharipovai}"
CONTAINER_USER="${SELF_HEALING_CONTAINER_USER:-10001:10001}"
RUNTIME_DIR="${SELF_HEALING_RUNTIME_DIR:-/var/lib/sharipovai/.self_healing}"
SNAPSHOT_DIR="$RUNTIME_DIR/git-metadata"
MARKER_FILE="$RUNTIME_DIR/git-metadata.marker"
WORK_TREE="${SELF_HEALING_WORK_TREE:-/workspace}"

fail() {
    printf 'self-healing git snapshot: %s\n' "$*" >&2
    exit 1
}

[[ "$CONTAINER_USER" =~ ^[0-9]+:[0-9]+$ ]] || fail "invalid container user: $CONTAINER_USER"
[ -d "$REPO_DIR/.git" ] || fail "Git repository is unavailable at $REPO_DIR"
command -v git >/dev/null 2>&1 || fail "host git is unavailable"
command -v docker >/dev/null 2>&1 || fail "host docker is unavailable"

docker inspect "$CONTAINER_NAME" >/dev/null 2>&1 || fail "container is unavailable: $CONTAINER_NAME"
[ "$(docker inspect -f '{{.State.Running}}' "$CONTAINER_NAME" 2>/dev/null || echo false)" = "true" ] || \
    fail "container is not running: $CONTAINER_NAME"

HEAD_SHA="$(git -C "$REPO_DIR" rev-parse --verify HEAD)"
[[ "$HEAD_SHA" =~ ^[0-9a-f]{40}$ ]] || fail "invalid HEAD SHA: $HEAD_SHA"

if [ -f "$REPO_DIR/.git/index" ]; then
    INDEX_SHA256="$(sha256sum "$REPO_DIR/.git/index" | awk '{print $1}')"
else
    INDEX_SHA256="missing"
fi
MARKER="$HEAD_SHA:$INDEX_SHA256"

verify_snapshot() {
    local actual
    actual="$(docker exec \
        --user "$CONTAINER_USER" \
        -e GIT_DIR="$SNAPSHOT_DIR" \
        -e GIT_WORK_TREE="$WORK_TREE" \
        -e GIT_OPTIONAL_LOCKS=0 \
        "$CONTAINER_NAME" \
        git -c "safe.directory=$WORK_TREE" -c core.filemode=false rev-parse --verify HEAD 2>/dev/null || true)"
    [ "$actual" = "$HEAD_SHA" ] || return 1

    docker exec \
        --user "$CONTAINER_USER" \
        -e GIT_DIR="$SNAPSHOT_DIR" \
        -e GIT_WORK_TREE="$WORK_TREE" \
        -e GIT_OPTIONAL_LOCKS=0 \
        "$CONTAINER_NAME" \
        git -c "safe.directory=$WORK_TREE" -c core.filemode=false status --porcelain --untracked-files=no \
        >/dev/null 2>&1
}

EXISTING_MARKER="$(docker exec --user "$CONTAINER_USER" "$CONTAINER_NAME" sh -ec \
    "test -f '$MARKER_FILE' && cat '$MARKER_FILE' || true" 2>/dev/null || true)"
if [ "$EXISTING_MARKER" = "$MARKER" ] && verify_snapshot; then
    printf '%s\n' "$HEAD_SHA"
    exit 0
fi

TEMP_DIR="$(mktemp -d -t sharipovai-self-healing-git.XXXXXX)"
trap 'rm -rf "$TEMP_DIR"' EXIT

# --no-hardlinks is deliberate: permissions on the sanitized snapshot must never
# affect the protected host .git object database through shared inodes.
git clone --quiet --no-checkout --no-hardlinks "$REPO_DIR" "$TEMP_DIR/repo"
SNAPSHOT_GIT="$TEMP_DIR/repo/.git"

git --git-dir="$SNAPSHOT_GIT" update-ref refs/heads/self-healing "$HEAD_SHA"
printf 'ref: refs/heads/self-healing\n' >"$SNAPSHOT_GIT/HEAD"

# Always use a clean HEAD index. The runtime worktree is compared against this
# immutable baseline, so staged and unstaged content changes remain detectable
# without importing host index stat/mode metadata into the unprivileged runtime.
rm -f "$SNAPSHOT_GIT/index"
GIT_INDEX_FILE="$SNAPSHOT_GIT/index" git --git-dir="$SNAPSHOT_GIT" read-tree "$HEAD_SHA"

# Do not copy host remote/credential configuration into the runtime snapshot.
# filemode=false is intentional: image/bind-mount permission differences must
# not become fake source changes. Content changes remain fully detectable.
cat >"$SNAPSHOT_GIT/config" <<'EOF'
[core]
    repositoryformatversion = 0
    filemode = false
    bare = false
    logallrefupdates = false
EOF
rm -rf "$SNAPSHOT_GIT/hooks" "$SNAPSHOT_GIT/logs"
mkdir -p "$SNAPSHOT_GIT/info"
cat >"$SNAPSHOT_GIT/info/exclude" <<'EOF'
# Host/runtime-only paths. These are never source changes for Self-Healing.
deploy/vps/backups/
deploy/vps/emergency-recovery/
deploy/vps/docker-compose.yml.bak-*
deploy/vps/.env*
*.db
*.db-wal
*.db-shm
*.sqlite
*.sqlite3
*.log
*.pyc
__pycache__/
.pytest_cache/
.mypy_cache/
.ruff_cache/
.venv/
venv/
EOF

# Extract as the unprivileged runtime UID. No chmod/chown is ever performed on
# the real repository metadata; only this private copy is made readable.
tar -C "$SNAPSHOT_GIT" -cf - . | docker exec -i --user "$CONTAINER_USER" "$CONTAINER_NAME" sh -ec "
    set -eu
    next='$SNAPSHOT_DIR.next'
    old='$SNAPSHOT_DIR.old'
    rm -rf \"\$next\" \"\$old\"
    install -d -m 0700 '$RUNTIME_DIR' \"\$next\"
    tar -xf - -C \"\$next\"
    chmod -R u+rwX,go-rwx \"\$next\"
    if [ -e '$SNAPSHOT_DIR' ]; then
        mv '$SNAPSHOT_DIR' \"\$old\"
    fi
    mv \"\$next\" '$SNAPSHOT_DIR'
    rm -rf \"\$old\"
"

printf '%s\n' "$MARKER" | docker exec -i --user "$CONTAINER_USER" "$CONTAINER_NAME" sh -ec \
    "cat > '$MARKER_FILE'; chmod 0600 '$MARKER_FILE'"

verify_snapshot || fail "sanitized Git snapshot verification failed"
printf '%s\n' "$HEAD_SHA"
