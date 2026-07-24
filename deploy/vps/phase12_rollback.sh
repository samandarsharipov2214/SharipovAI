#!/usr/bin/env bash
set -Eeuo pipefail
umask 027
CONFIRMATION="${1:-}"
TARGET_SHA="${SHARIPOVAI_ROLLBACK_SHA:-}"
CURRENT_SHA="${SHARIPOVAI_EXPECTED_SHA:-}"
ROOT="${SHARIPOVAI_ROOT:-${APP_DIR:-/opt/sharipovai-repo}}"
EVIDENCE="${PHASE12_ROLLBACK_OUTPUT:-/var/lib/sharipovai/audit/phase12-rollback.json}"
fail(){ printf 'PHASE12_ROLLBACK_BLOCKED: %s\n' "$*" >&2; exit 2; }
[[ "$CONFIRMATION" == "I_APPROVE_PHASE12_EXACT_SHA_ROLLBACK" ]] || fail "exact Phase 12 rollback confirmation is required"
[[ "$TARGET_SHA" =~ ^[0-9a-f]{40}$ ]] || fail "rollback target must be a full SHA"
[[ "$CURRENT_SHA" =~ ^[0-9a-f]{40}$ ]] || fail "current approved SHA must be a full SHA"
[[ -d "$ROOT/.git" ]] || fail "canonical repository is missing"
cd "$ROOT"
[[ "$(git rev-parse HEAD)" == "$CURRENT_SHA" ]] || fail "current checkout differs from approved SHA"
git merge-base --is-ancestor "$TARGET_SHA" "$CURRENT_SHA" || fail "rollback target is not an ancestor"
SHARIPOVAI_ROLLBACK_SHA="$TARGET_SHA" SHARIPOVAI_EXPECTED_SHA="$CURRENT_SHA" bash deploy/vps/phase11_rollback.sh I_APPROVE_PHASE11_EXACT_SHA_ROLLBACK
[[ "$(git rev-parse HEAD)" == "$TARGET_SHA" ]] || fail "rollback checkout SHA mismatch"
if git cat-file -e "$TARGET_SHA:deploy/vps/phase12_post_deploy_verify.sh" 2>/dev/null; then
  SHARIPOVAI_EXPECTED_SHA="$TARGET_SHA" bash deploy/vps/phase12_post_deploy_verify.sh
else
  SHARIPOVAI_EXPECTED_SHA="$TARGET_SHA" bash deploy/vps/phase11_post_deploy_verify.sh
fi
install -d -m 0750 "$(dirname "$EVIDENCE")"
tmp="$(mktemp "$(dirname "$EVIDENCE")/.phase12-rollback.XXXXXX")"
trap 'rm -f "$tmp"' EXIT
printf '{"status":"rolled_back","from_sha":"%s","to_sha":"%s","mainnet_enabled":false}\n' "$CURRENT_SHA" "$TARGET_SHA" >"$tmp"
chmod 0640 "$tmp"
mv -f "$tmp" "$EVIDENCE"
trap - EXIT
printf 'PHASE12_ROLLBACK_OK from=%s to=%s evidence=%s\n' "$CURRENT_SHA" "$TARGET_SHA" "$EVIDENCE"
