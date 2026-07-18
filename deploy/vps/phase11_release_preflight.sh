#!/usr/bin/env bash
set -Eeuo pipefail
umask 027

ROOT="${SHARIPOVAI_ROOT:-/opt/sharipovai}"
EXPECTED_SHA="${SHARIPOVAI_EXPECTED_SHA:-}"
fail(){ printf 'PHASE11_PREFLIGHT_BLOCKED: %s\n' "$*" >&2; exit 2; }

[[ -d "$ROOT/.git" ]] || fail "release root is not a Git worktree"
cd "$ROOT"
[[ -n "$EXPECTED_SHA" ]] || fail "SHARIPOVAI_EXPECTED_SHA is required"
ACTUAL_SHA="$(git rev-parse HEAD)"
[[ "$ACTUAL_SHA" == "$EXPECTED_SHA" ]] || fail "deployed SHA does not match approved SHA"
git diff --quiet -- || fail "tracked worktree changes are present"
git diff --cached --quiet -- || fail "staged worktree changes are present"
[[ -z "$(git status --porcelain --untracked-files=normal)" ]] || fail "worktree is not clean"

[[ "${EXECUTION_KILL_SWITCH:-1}" == "1" ]] || fail "kill switch must be engaged"
[[ "${EXCHANGE_LIVE_TRADING_ENABLED:-0}" == "0" ]] || fail "live execution must remain disabled"
[[ "${FEATURE_BYBIT_LIVE_EXECUTION:-0}" == "0" ]] || fail "live feature flag must remain disabled"
[[ "${FEATURE_BYBIT_TESTNET_EXECUTION:-0}" == "0" ]] || fail "Testnet feature flag must remain disabled before the finite window"
[[ "${TESTNET_EXECUTION_ENABLED:-0}" == "0" ]] || fail "Testnet execution must remain disabled before the finite window"
[[ "${AUTONOMOUS_TESTNET_ENABLED:-0}" == "0" ]] || fail "autonomous Testnet must remain disabled"
[[ "${AUTONOMOUS_TESTNET_BRIDGE_ENABLED:-0}" == "0" ]] || fail "Testnet bridge must remain disabled"
[[ "${FEATURE_BYBIT_PRIVATE_ORDER_WS:-0}" == "0" ]] || fail "private stream must remain disabled before operator activation"
[[ "${BYBIT_ALLOW_LEGACY_EXCHANGE_CREDENTIALS:-0}" == "0" ]] || fail "legacy credentials must remain disabled"
[[ "${SHARIPOVAI_DISABLE_AUTH:-0}" == "0" ]] || fail "authentication must remain enabled"
[[ -n "${AUTH_SECRET:-}" ]] || fail "AUTH_SECRET is required"
[[ -n "${ADMIN_USERNAME:-}" ]] || fail "ADMIN_USERNAME is required"
[[ -n "${ADMIN_PASSWORD:-}" ]] || fail "ADMIN_PASSWORD is required"
[[ "${SHARIPOVAI_DATABASE_REQUIRED:-1}" == "1" ]] || fail "canonical database must be required"
[[ "${EXCHANGE_MODE:-sandbox}" == "sandbox" ]] || fail "exchange mode must remain sandbox"
[[ -n "${DATABASE_URL:-}" ]] || fail "DATABASE_URL is required"

python - <<'PY'
import math
import os
value = float(os.getenv("PHASE11_MAX_TESTNET_NOTIONAL_USDT", "50"))
if not math.isfinite(value) or not 0 < value <= 50:
    raise SystemExit("Testnet ceiling must be finite and within (0, 50]")
PY

python -m pip check
python -m compileall -q .
python -m pytest \
  tests/test_phase10_controlled_scaling.py \
  tests/test_phase10_capital_engine.py \
  tests/test_phase11_production_audit.py \
  tests/test_phase11_dashboard_contract.py \
  tests/test_phase11_crash_resilience.py \
  -q --tb=short

python - <<'PY'
import json
from audit.phase11_production_audit import ProductionAudit
from storage import ProjectDatabase

database = ProjectDatabase().health()
if database.get("status") != "ok":
    raise SystemExit("canonical database health check failed")
report = ProductionAudit(".").run()
print(json.dumps({"database": database, "audit": report}, indent=2, sort_keys=True))
raise SystemExit(0 if report["status"] == "ready_for_bounded_testnet_preflight" else 2)
PY

printf 'PHASE11_PREFLIGHT_OK sha=%s\n' "$ACTUAL_SHA"
