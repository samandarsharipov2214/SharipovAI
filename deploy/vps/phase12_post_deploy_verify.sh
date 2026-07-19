#!/usr/bin/env bash
set -Eeuo pipefail
umask 027
ROOT="${SHARIPOVAI_ROOT:-${APP_DIR:-/opt/sharipovai-repo}}"
EXPECTED_SHA="${SHARIPOVAI_EXPECTED_SHA:-}"
CONTAINER="${PHASE12_CONTAINER_NAME:-sharipovai}"
OUT="${PHASE12_VERIFY_OUTPUT:-/var/lib/sharipovai/audit/phase12-post-deploy.json}"
fail(){ printf 'PHASE12_POST_DEPLOY_BLOCKED: %s\n' "$*" >&2; exit 2; }
[[ "$EXPECTED_SHA" =~ ^[0-9a-f]{40}$ ]] || fail "full approved SHA is required"
[[ "$CONTAINER" =~ ^[A-Za-z0-9_.-]+$ ]] || fail "invalid container name"
[[ -d "$ROOT/.git" ]] || fail "release root is not a Git worktree"
cd "$ROOT"
[[ "$(git rev-parse HEAD)" == "$EXPECTED_SHA" ]] || fail "host SHA mismatch"
[[ -z "$(git status --porcelain --untracked-files=normal)" ]] || fail "host worktree is not clean"
SHARIPOVAI_EXPECTED_SHA="$EXPECTED_SHA" bash deploy/vps/phase11_post_deploy_verify.sh
RUNTIME_SHA="$(docker exec "$CONTAINER" printenv SHARIPOVAI_BUILD_SHA 2>/dev/null || true)"
LABEL_SHA="$(docker inspect --format '{{ index .Config.Labels "org.opencontainers.image.revision" }}' "$CONTAINER" 2>/dev/null || true)"
[[ "$RUNTIME_SHA" == "$EXPECTED_SHA" ]] || fail "container runtime SHA mismatch"
[[ "$LABEL_SHA" == "$EXPECTED_SHA" ]] || fail "container image revision mismatch"
install -d -m 0750 "$(dirname "$OUT")"
tmp="$(mktemp "$(dirname "$OUT")/.phase12-runtime.XXXXXX")"
trap 'rm -f "$tmp"' EXIT
docker exec "$CONTAINER" python - <<'PY' >"$tmp"
import json
from learning_engine import SelfLearningSupervisor
from storage import ProjectDatabase
from validation import Phase12FillValidationService

database = ProjectDatabase()
status = SelfLearningSupervisor(database).status()
report = {
    "database": database.health(),
    "self_learning": status,
    "fill_validation_service": type(Phase12FillValidationService(database)).__name__,
    "execution_authority": False,
    "automatic_execution_promotion": False,
    "mainnet_enabled": False,
}
print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False))
raise SystemExit(0 if report["database"].get("status") == "ok" else 2)
PY
chmod 0640 "$tmp"
mv -f "$tmp" "$OUT"
trap - EXIT
printf 'PHASE12_POST_DEPLOY_OK sha=%s output=%s\n' "$EXPECTED_SHA" "$OUT"
