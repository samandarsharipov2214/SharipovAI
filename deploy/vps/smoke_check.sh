#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

MODE="${1:-production}"
COMPOSE_DIR="${COMPOSE_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}"
BASE_ENV_FILE="${BASE_ENV_FILE:-${COMPOSE_DIR}/.env.vps}"
CAMPAIGN_ENV_FILE="${CAMPAIGN_ENV_FILE:-${COMPOSE_DIR}/.env.testnet-campaign}"
HEALTH_URL="${HEALTH_URL:-http://127.0.0.1:8000/health}"
ATTEMPTS="${HEALTH_ATTEMPTS:-45}"
DELAY="${HEALTH_DELAY_SECONDS:-2}"

fail() { printf '[smoke-check] ERROR: %s\n' "$*" >&2; exit 1; }
log() { printf '[smoke-check] %s\n' "$*"; }

[[ "${MODE}" == "production" || "${MODE}" == "testnet-campaign" ]] || fail "unsupported mode: ${MODE}"
[[ -f "${BASE_ENV_FILE}" ]] || fail "missing base env file: ${BASE_ENV_FILE}"
validator=(python3 "${COMPOSE_DIR}/validate_runtime_env.py" --env-file "${BASE_ENV_FILE}" --mode "${MODE}")
compose=(docker compose --project-directory "${COMPOSE_DIR}" -f "${COMPOSE_DIR}/docker-compose.yml" --env-file "${BASE_ENV_FILE}")
if [[ "${MODE}" == "testnet-campaign" ]]; then
  [[ -f "${CAMPAIGN_ENV_FILE}" ]] || fail "missing campaign env file: ${CAMPAIGN_ENV_FILE}"
  validator=(python3 "${COMPOSE_DIR}/validate_runtime_env.py" --env-file "${BASE_ENV_FILE}" --env-file "${CAMPAIGN_ENV_FILE}" --mode "${MODE}")
  compose=(docker compose --project-directory "${COMPOSE_DIR}" -f "${COMPOSE_DIR}/docker-compose.yml" -f "${COMPOSE_DIR}/docker-compose.testnet-campaign.yml" --env-file "${CAMPAIGN_ENV_FILE}")
fi
"${validator[@]}"

rendered="$(mktemp)"
trap 'rm -f "${rendered}"' EXIT
"${compose[@]}" config --format json >"${rendered}"
python3 - "${rendered}" "${MODE}" <<'PY'
import json
import sys
from pathlib import Path

payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
production_mode = sys.argv[2] == "production"
service = payload.get("services", {}).get("sharipovai", {})
environment = service.get("environment", {})
if isinstance(environment, list):
    environment = dict(item.split("=", 1) for item in environment if "=" in item)

required = {
    "EXCHANGE_LIVE_TRADING_ENABLED": "0",
    "FEATURE_BYBIT_LIVE_EXECUTION": "0",
}
if production_mode:
    required["EXECUTION_KILL_SWITCH"] = "1"
else:
    required.update(
        {
            "EXCHANGE_MODE": "sandbox",
            "EXCHANGE_BASE_URL": "https://api-testnet.bybit.com",
            "EXECUTION_KILL_SWITCH": "0",
            "TESTNET_EXECUTION_ENABLED": "1",
            "AUTONOMOUS_TESTNET_ENABLED": "1",
            "AUTONOMOUS_TESTNET_BRIDGE_ENABLED": "1",
            "FEATURE_BYBIT_TESTNET": "1",
            "FEATURE_BYBIT_PRIVATE_ORDER_WS": "1",
            "RUNTIME_FILL_HARVESTER_ENABLED": "1",
            "SCHEDULED_CAMPAIGN_ORCHESTRATOR_ENABLED": "1",
            "CRITICAL_ALERT_MONITOR_ENABLED": "1",
            "PHASE6_TESTNET_RELEASE_GATE": "green",
        }
    )
    if not str(environment.get("BYBIT_TESTNET_API_KEY", "")).strip():
        raise SystemExit("unsafe rendered compose: BYBIT_TESTNET_API_KEY is missing")
    if not str(environment.get("BYBIT_TESTNET_API_SECRET", "")).strip():
        raise SystemExit("unsafe rendered compose: BYBIT_TESTNET_API_SECRET is missing")

for key, expected in required.items():
    actual = str(environment.get(key, ""))
    if actual != expected:
        raise SystemExit(f"unsafe rendered compose: {key}={actual!r}, expected {expected!r}")

if production_mode:
    for key in (
        "TESTNET_EXECUTION_ENABLED",
        "AUTONOMOUS_TESTNET_ENABLED",
        "AUTONOMOUS_TESTNET_BRIDGE_ENABLED",
        "FEATURE_BYBIT_TESTNET",
        "FEATURE_BYBIT_PRIVATE_ORDER_WS",
        "RUNTIME_FILL_HARVESTER_ENABLED",
        "SCHEDULED_CAMPAIGN_ORCHESTRATOR_ENABLED",
    ):
        if str(environment.get(key, "0")).strip().lower() in {"1", "true", "yes", "on"}:
            raise SystemExit(f"unsafe production compose: {key} enabled")
PY

for ((attempt = 1; attempt <= ATTEMPTS; attempt++)); do
  if curl --fail --silent --show-error --max-time 5 "${HEALTH_URL}" >/dev/null; then
    break
  fi
  [[ ${attempt} -lt ${ATTEMPTS} ]] || fail "health endpoint did not recover: ${HEALTH_URL}"
  sleep "${DELAY}"
done

state="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' sharipovai 2>/dev/null || true)"
[[ "${state}" == "healthy" || "${state}" == "running" ]] || fail "unexpected container state: ${state:-missing}"

docker exec sharipovai python - <<'PY'
from storage import ProjectDatabase

health = ProjectDatabase().health()
if health.get("status") != "ok":
    raise SystemExit(f"database health failed: {health}")
print(health)
PY
log "SMOKE_OK mode=${MODE} container=${state}"
