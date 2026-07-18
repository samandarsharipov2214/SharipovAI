#!/usr/bin/env bash
set -Eeuo pipefail
umask 027

ROOT="${SHARIPOVAI_ROOT:-/opt/sharipovai}"
OUT="${PHASE11_VERIFY_OUTPUT:-/var/lib/sharipovai/audit/phase11-post-deploy.json}"
HEALTH_URL="${SHARIPOVAI_HEALTH_URL:-http://127.0.0.1:8000/api/health}"
EXPECTED_SHA="${SHARIPOVAI_EXPECTED_SHA:-}"
[[ -d "$ROOT/.git" ]] || { echo "release root is not a Git worktree" >&2; exit 2; }
[[ -n "$EXPECTED_SHA" ]] || { echo "SHARIPOVAI_EXPECTED_SHA is required" >&2; exit 2; }
cd "$ROOT"
ACTUAL_SHA="$(git rev-parse HEAD)"
[[ "$ACTUAL_SHA" == "$EXPECTED_SHA" ]] || { echo "deployed SHA mismatch" >&2; exit 2; }

mkdir -p "$(dirname "$OUT")"
health_file="$(mktemp "$(dirname "$OUT")/.phase11-health.XXXXXX")"
trap 'rm -f "$health_file"' EXIT
curl --fail --silent --show-error --max-time 10 --retry 2 --retry-all-errors "$HEALTH_URL" >"$health_file"
chmod 0600 "$health_file"
python -m compileall -q .

PHASE11_HEALTH_FILE="$health_file" PHASE11_VERIFY_OUTPUT="$OUT" PHASE11_DEPLOYED_SHA="$ACTUAL_SHA" python - <<'PY'
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
status = "ready_for_bounded_testnet_preflight"
blockers = list(audit.get("blockers") or [])
if database.get("status") != "ok":
    blockers.append("canonical_database_health")
if audit.get("status") != "ready_for_bounded_testnet_preflight":
    status = "blocked"
if blockers:
    status = "blocked"

report = {
    **audit,
    "status": status,
    "blockers": sorted(set(blockers)),
    "verified_at_ms": int(time.time() * 1000),
    "deployed_sha": os.environ["PHASE11_DEPLOYED_SHA"],
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

printf 'PHASE11_POST_DEPLOY_OK output=%s sha=%s\n' "$OUT" "$ACTUAL_SHA"
