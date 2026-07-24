#!/usr/bin/env bash
set -Eeuo pipefail
umask 027
ROOT="${SHARIPOVAI_ROOT:-${APP_DIR:-/opt/sharipovai-repo}}"
EXPECTED_SHA="${SHARIPOVAI_EXPECTED_SHA:-}"
OUT="${PHASE12_PREFLIGHT_OUTPUT:-/var/lib/sharipovai/audit/phase12-preflight.json}"
fail(){ printf 'PHASE12_PREFLIGHT_BLOCKED: %s\n' "$*" >&2; exit 2; }
[[ "$EXPECTED_SHA" =~ ^[0-9a-f]{40}$ ]] || fail "full approved SHA is required"
[[ -d "$ROOT/.git" ]] || fail "release root is not a Git worktree"
cd "$ROOT"
[[ "$(git rev-parse HEAD)" == "$EXPECTED_SHA" ]] || fail "checked-out SHA differs from approved SHA"
[[ -z "$(git status --porcelain --untracked-files=normal)" ]] || fail "worktree is not clean"
for path in learning_engine/evidence_policy.py learning_engine/outcome_attribution.py learning_engine/research_challengers.py learning_engine/self_learning_supervisor.py validation/paper_fill_validation.py validation/phase12_validation.py scripts/phase12_premerge_checklist.py deploy/vps/phase12_post_deploy_verify.sh deploy/vps/phase12_rollback.sh; do
  git cat-file -e "$EXPECTED_SHA:$path" 2>/dev/null || fail "approved commit misses $path"
done
SHARIPOVAI_EXPECTED_SHA="$EXPECTED_SHA" bash deploy/vps/phase11_release_preflight.sh
install -d -m 0750 "$(dirname "$OUT")"
tmp="$(mktemp "$(dirname "$OUT")/.phase12-preflight.XXXXXX")"
trap 'rm -f "$tmp"' EXIT
python scripts/phase12_premerge_checklist.py --root "$ROOT" --expected-sha "$EXPECTED_SHA" >"$tmp"
chmod 0640 "$tmp"
mv -f "$tmp" "$OUT"
trap - EXIT
printf 'PHASE12_PREFLIGHT_OK root=%s sha=%s evidence=%s\n' "$ROOT" "$EXPECTED_SHA" "$OUT"
