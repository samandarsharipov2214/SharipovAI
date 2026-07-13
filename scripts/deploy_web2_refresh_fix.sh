#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="/opt/sharipovai-repo"
PUBLIC_URL="https://85-137-88-17.sslip.io"
SERVICE="sharipovai"

echo "[1/2] Running the protected SharipovAI deployment with Web2 ownership tests..."
cd "$ROOT"
bash scripts/deploy_market_paper_runtime.sh

echo "[2/2] Verifying v27 currencies, explanations, source status and public HTTPS health..."
docker exec "$SERVICE" sh -lc '
set -Eeuo pipefail
index=/app/dashboard/static/web2/index.html
grep -F "navigation_coordinator_v23.js?v=25" "$index" >/dev/null
grep -F "web2.js?v=26" "$index" >/dev/null
grep -F "system_status_v11.js?v=26" "$index" >/dev/null
grep -F "overview_runtime_v25.js?v=27" "$index" >/dev/null
grep -F "decision_runtime_v25.js?v=25" "$index" >/dev/null
grep -F "learning_runtime_v25.js?v=25" "$index" >/dev/null
grep -F "exchange_execution_settings_v18.js?v=27" "$index" >/dev/null
grep -F "/api/exchange/account/status" /app/dashboard/static/web2/web2.js >/dev/null
grep -F "основных API" /app/dashboard/static/web2/web2.js >/dev/null
grep -F "НЕ НАСТРОЕН" /app/dashboard/static/web2/system_status_v11.js >/dev/null
grep -F "ADAUSDT" /app/dashboard/static/web2/overview_runtime_v25.js >/dev/null
grep -F "Почему ИИ открыл или закрыл" /app/dashboard/static/web2/overview_runtime_v25.js >/dev/null
grep -F "maximumFractionDigits:1" /app/dashboard/static/web2/overview_runtime_v25.js >/dev/null
grep -F "Почему открыта" /app/dashboard/static/web2/exchange_execution_settings_v18.js >/dev/null
grep -F "Почему закрыта" /app/dashboard/static/web2/exchange_execution_settings_v18.js >/dev/null
python -m py_compile /app/dashboard/trade_explanations.py /app/dashboard/paper_activity_api.py
'
docker exec -e PYTHONPATH=/app "$SERVICE" python - <<'PY'
from dashboard.app import app
from market_paper_engine import PaperActivityEngine

routes = {getattr(route, "path", ""): route for route in app.routes}
for path in (
    "/api/learning-os/status",
    "/api/evidence-vault/recent",
    "/api/exchange/account/status",
    "/api/virtual-account/trades",
):
    assert path in routes, f"missing source route: {path}"

learning = routes["/api/learning-os/status"].endpoint()
evidence = routes["/api/evidence-vault/recent"].endpoint()
trades_payload = routes["/api/virtual-account/trades"].endpoint()
assert learning.get("status") == "ok" and isinstance(learning.get("items"), list)
assert evidence.get("status") == "ok" and isinstance(evidence.get("items"), list)
assert trades_payload.get("status") == "ok" and isinstance(trades_payload.get("trades"), list)
for trade in trades_payload.get("trades", []):
    assert trade.get("entry_reason_ru"), f"missing entry explanation: {trade.get('id')}"
    assert trade.get("operation_explanation_ru"), f"missing operation explanation: {trade.get('id')}"
print("SOURCE_AND_EXPLANATION_CONTRACTS_OK")

state = PaperActivityEngine().state()
assert isinstance(state.get("trades"), list), "virtual trade list missing"
assert state.get("summary", {}).get("market_price_accounting") is True, "market accounting not confirmed"
assert state.get("summary", {}).get("real_orders_blocked") is True, "real orders are not blocked"
print("WEB2_VIRTUAL_DATA_OK")
PY
curl --fail --silent --show-error "$PUBLIC_URL/health"
echo
echo "Web2 v27 currencies, readable precision and explainable operations deployed and verified."
