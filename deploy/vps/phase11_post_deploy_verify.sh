#!/usr/bin/env bash
set -Eeuo pipefail
umask 027

ROOT="${SHARIPOVAI_ROOT:-${APP_DIR:-/opt/sharipovai-repo}}"
OUT="${PHASE11_VERIFY_OUTPUT:-/var/lib/sharipovai/audit/phase11-post-deploy.json}"
HEALTH_URL="${SHARIPOVAI_HEALTH_URL:-http://127.0.0.1:8000/api/health}"
EXPECTED_SHA="${SHARIPOVAI_EXPECTED_SHA:-}"
CONTAINER_NAME="${PHASE11_CONTAINER_NAME:-sharipovai}"
[[ "$CONTAINER_NAME" =~ ^[A-Za-z0-9_.-]+$ ]] || { echo "invalid container name" >&2; exit 2; }
[[ -d "$ROOT/.git" ]] || { echo "release root is not a Git worktree" >&2; exit 2; }
[[ -n "$EXPECTED_SHA" ]] || { echo "SHARIPOVAI_EXPECTED_SHA is required" >&2; exit 2; }
command -v docker >/dev/null || { echo "docker is required" >&2; exit 2; }
cd "$ROOT"
ACTUAL_SHA="$(git rev-parse HEAD)"
[[ "$ACTUAL_SHA" == "$EXPECTED_SHA" ]] || { echo "deployed SHA mismatch" >&2; exit 2; }
[[ -z "$(git status --porcelain --untracked-files=normal)" ]] || { echo "deployed worktree is not clean" >&2; exit 2; }
docker inspect "$CONTAINER_NAME" >/dev/null 2>&1 || { echo "application container is missing" >&2; exit 2; }

mkdir -p "$(dirname "$OUT")"
health_file="$(mktemp "$(dirname "$OUT")/.phase11-health.XXXXXX")"
trap 'rm -f "$health_file"' EXIT
curl --fail --silent --show-error --max-time 10 --retry 2 --retry-all-errors "$HEALTH_URL" >"$health_file"
chmod 0600 "$health_file"
python -m compileall -q .

PHASE11_HEALTH_FILE="$health_file" PHASE11_VERIFY_OUTPUT="$OUT" PHASE11_DEPLOYED_SHA="$ACTUAL_SHA" PHASE11_DEPLOYED_ROOT="$ROOT" python - <<'PY'
import json
import os
import tempfile
import time
from pathlib import Path

from audit.phase11_production_audit import ProductionAudit
from storage import ProjectDatabase

output = Path(os.environ["PHASE11_VERIFY_OUTPUT"]).expanduser().resolve()
health_path = Path(os.environ["PHASE11_HEALTH_FILE"]).resolve()
with health_path.open("r", encoding="utf-8") as handle:
    http_health = json.load(handle)
if not isinstance(http_health, dict) or str(http_health.get("status") or "").lower() != "ok":
    raise SystemExit("public liveness endpoint is not healthy")

database = ProjectDatabase().health()
audit = ProductionAudit(".").run()
blockers = list(audit.get("blockers") or [])
if database.get("status") != "ok":
    blockers.append("canonical_database_health")
status = (
    "ready_for_bounded_testnet_preflight"
    if audit.get("status") == "ready_for_bounded_testnet_preflight" and not blockers
    else "blocked"
)
report = {
    **audit,
    "status": status,
    "blockers": sorted(set(blockers)),
    "verified_at_ms": int(time.time() * 1000),
    "deployed_sha": os.environ["PHASE11_DEPLOYED_SHA"],
    "deployed_root": os.environ["PHASE11_DEPLOYED_ROOT"],
    "http_health": http_health,
    "database_health": database,
}
serialized = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n"
output.parent.mkdir(parents=True, exist_ok=True)
file_descriptor, temporary_name = tempfile.mkstemp(prefix=f".{output.name}.", dir=output.parent)
temporary = Path(temporary_name)
try:
    with os.fdopen(file_descriptor, "w", encoding="utf-8") as handle:
        handle.write(serialized)
        handle.flush()
        os.fsync(handle.fileno())
    os.chmod(temporary, 0o640)
    os.replace(temporary, output)
    directory_fd = os.open(output.parent, os.O_RDONLY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)
finally:
    temporary.unlink(missing_ok=True)

print(serialized, end="")
raise SystemExit(0 if status == "ready_for_bounded_testnet_preflight" else 2)
PY

REMOTE_DIR="/var/lib/sharipovai/audit"
REMOTE_OUT="$REMOTE_DIR/phase11-post-deploy.json"
REMOTE_TMP="$REMOTE_DIR/.phase11-post-deploy.$ACTUAL_SHA.tmp"
docker exec --user 0 "$CONTAINER_NAME" install -d -m 0750 -o 10001 -g 10001 "$REMOTE_DIR"
docker cp "$OUT" "$CONTAINER_NAME:$REMOTE_TMP"
docker exec --user 0 "$CONTAINER_NAME" chown 10001:10001 "$REMOTE_TMP"
docker exec --user 0 "$CONTAINER_NAME" chmod 0640 "$REMOTE_TMP"
docker exec --user 0 "$CONTAINER_NAME" mv -f "$REMOTE_TMP" "$REMOTE_OUT"
docker exec "$CONTAINER_NAME" test -r "$REMOTE_OUT"

printf 'PHASE11_POST_DEPLOY_OK root=%s output=%s container=%s sha=%s\n' "$ROOT" "$OUT" "$CONTAINER_NAME" "$ACTUAL_SHA"
