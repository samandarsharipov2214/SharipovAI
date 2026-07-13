#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="/opt/sharipovai-repo"
PUBLIC_URL="https://85-137-88-17.sslip.io"
SERVICE="sharipovai"

echo "[1/2] Running the protected SharipovAI deployment with Web2 ownership tests..."
cd "$ROOT"
bash scripts/deploy_market_paper_runtime.sh

echo "[2/2] Verifying v26 source status, interface files, virtual-account data and public HTTPS health..."
docker exec "$SERVICE" sh -lc '
set -Eeuo pipefail
index=/app/dashboard/static/web2/index.html
grep -F "navigation_coordinator_v23.js?v=25" "$index" >/dev/null
grep -F "web2.js?v=26" "$index" >/dev/null
grep -F "system_status_v11.js?v=26" "$index" >/dev/null
grep -F "overview_runtime_v25.js?v=25" "$index" >/dev/null
grep -F "decision_runtime_v25.js?v=25" "$index" >/dev/null
grep -F "learning_runtime_v25.js?v=25" "$index" >/dev/null
grep -F "exchange_execution_settings_v18.js?v=25" "$index" >/dev/null
grep -F "/api/exchange/account/status" /app/dashboard/static/web2/web2.js >/dev/null
grep -F "основных API" /app/dashboard/static/web2/web2.js >/dev/null
grep -F "НЕ НАСТРОЕН" /app/dashboard/static/web2/system_status_v11.js >/dev/null
grep -F "/api/virtual-account/state" /app/dashboard/static/web2/overview_runtime_v25.js >/dev/null
grep -F "Каноническое решение" /app/dashboard/static/web2/decision_runtime_v25.js >/dev/null
grep -F "/api/virtual-account/trades" /app/dashboard/static/web2/learning_runtime_v25.js >/dev/null
'
docker exec -e PYTHONPATH=/app "$SERVICE" python - <<'PY'
from dashboard.app import app
from market_paper_engine import PaperActivityEngine

routes = {getattr(route, "path", ""): route for route in app.routes}
for path in (
    "/api/learning-os/status",
    "/api/evidence-vault/recent",
    "/api/exchange/account/status",
):
    assert path in routes, f"missing source route: {path}"

learning = routes["/api/learning-os/status"].endpoint()
evidence = routes["/api/evidence-vault/recent"].endpoint()
assert learning.get("status") == "ok" and isinstance(learning.get("items"), list)
assert evidence.get("status") == "ok" and isinstance(evidence.get("items"), list)
print("SOURCE_STATUS_CONTRACTS_OK")

state = PaperActivityEngine().state()
assert isinstance(state.get("trades"), list), "virtual trade list missing"
assert state.get("summary", {}).get("market_price_accounting") is True, "market accounting not confirmed"
assert state.get("summary", {}).get("real_orders_blocked") is True, "real orders are not blocked"
print("WEB2_VIRTUAL_DATA_OK")
PY
curl --fail --silent --show-error "$PUBLIC_URL/health"
echo
echo "Web2 v26 source availability and single-owner interface deployed and verified."
