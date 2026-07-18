#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="${SHARIPOVAI_ROOT:-/opt/sharipovai}"
cd "$ROOT"
fail(){ echo "PHASE11_PREFLIGHT_BLOCKED: $*" >&2; exit 2; }
[[ "${EXECUTION_KILL_SWITCH:-1}" == "1" ]] || fail "kill switch must be engaged"
[[ "${EXCHANGE_LIVE_TRADING_ENABLED:-0}" == "0" ]] || fail "Mainnet/live execution must remain disabled"
[[ "${FEATURE_BYBIT_LIVE_EXECUTION:-0}" == "0" ]] || fail "live feature flag must remain disabled"
[[ "${PHASE11_MAX_TESTNET_NOTIONAL_USDT:-50}" =~ ^([0-9]+)(\.[0-9]+)?$ ]] || fail "invalid Testnet ceiling"
python - <<'PY'
import os
v=float(os.getenv('PHASE11_MAX_TESTNET_NOTIONAL_USDT','50'))
assert 0 < v <= 50, 'Testnet ceiling must be <= 50 USDT'
PY
python -m compileall -q .
python -m pytest tests/test_phase11_production_audit.py tests/test_phase11_dashboard_contract.py -q --tb=short
python - <<'PY'
import json
from audit.phase11_production_audit import ProductionAudit
r=ProductionAudit('.').run()
print(json.dumps(r,indent=2,sort_keys=True))
raise SystemExit(0 if r['status']=='ready_for_bounded_testnet_preflight' else 2)
PY
