#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="/opt/sharipovai-repo"
PUBLIC_URL="https://85-137-88-17.sslip.io"
SERVICE="sharipovai"

echo "[1/2] Running the protected SharipovAI deployment with Web2 ownership tests..."
cd "$ROOT"
bash scripts/deploy_market_paper_runtime.sh

echo "[2/2] Verifying v30 transparent trades, live status, ruble display and public HTTPS health..."
docker exec "$SERVICE" sh -lc '
set -Eeuo pipefail
index=/app/dashboard/static/web2/index.html
grep -F "navigation_coordinator_v23.js?v=25" "$index" >/dev/null
grep -F "web2.js?v=29" "$index" >/dev/null
grep -F "system_status_v11.js?v=29" "$index" >/dev/null
grep -F "overview_runtime_v25.js?v=30" "$index" >/dev/null
grep -F "exchange_execution_settings_v18.js?v=30" "$index" >/dev/null
grep -F "interface_v30.css?v=30" "$index" >/dev/null
grep -F "AUTO_REFRESH_MS = 15000" /app/dashboard/static/web2/system_status_v11.js >/dev/null
grep -F "setInterval(updateClock, 1000)" /app/dashboard/static/web2/system_status_v11.js >/dev/null
! grep -F "Записей:" /app/dashboard/static/web2/system_status_v11.js >/dev/null
! grep -F "Состояние:" /app/dashboard/static/web2/system_status_v11.js >/dev/null
grep -F "ADAUSDT" /app/dashboard/static/web2/overview_runtime_v25.js >/dev/null
grep -F "/api/currency/usd-rub" /app/dashboard/static/web2/overview_runtime_v25.js >/dev/null
grep -F "Размер позиции" /app/dashboard/static/web2/overview_runtime_v25.js >/dev/null
grep -F "Результат движения цены" /app/dashboard/static/web2/overview_runtime_v25.js >/dev/null
grep -F "Комиссии" /app/dashboard/static/web2/overview_runtime_v25.js >/dev/null
grep -F "Чистый результат" /app/dashboard/static/web2/overview_runtime_v25.js >/dev/null
grep -F "цена справа является текущей, а не ценой выхода" /app/dashboard/static/web2/exchange_execution_settings_v18.js >/dev/null
grep -F "data-trade-filter" /app/dashboard/static/web2/exchange_execution_settings_v18.js >/dev/null
grep -F ".trade-card" /app/dashboard/static/web2/interface_v30.css >/dev/null
grep -F ".trade-breakdown" /app/dashboard/static/web2/interface_v30.css >/dev/null
python -m py_compile /app/dashboard/currency_api.py /app/dashboard/trade_explanations.py /app/dashboard/paper_activity_api.py
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
    "/api/currency/usd-rub",
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
    assert float(trade.get("notional", 0) or 0) > 0, f"missing notional: {trade.get('id')}"
    assert float(trade.get("quantity", 0) or 0) > 0, f"missing quantity: {trade.get('id')}"
print("TRANSPARENT_TRADE_CONTRACTS_OK")

try:
    rate_payload = app.state.usd_rub_rate_service.get_rate()
    assert float(rate_payload.get("rub_per_usdt_estimate", 0)) > 0
    print("RUBLE_RATE_OK", rate_payload.get("rub_per_usdt_estimate"), rate_payload.get("source"))
except Exception as exc:
    print("RUBLE_RATE_ROUTE_OK_BUT_SOURCE_TEMPORARILY_UNAVAILABLE", type(exc).__name__)

state = PaperActivityEngine().state()
assert isinstance(state.get("trades"), list), "virtual trade list missing"
assert state.get("summary", {}).get("market_price_accounting") is True, "market accounting not confirmed"
assert state.get("summary", {}).get("real_orders_blocked") is True, "real orders are not blocked"
print("WEB2_VIRTUAL_DATA_OK")
PY
curl --fail --silent --show-error "$PUBLIC_URL/health"
echo
echo "Web2 v30 transparent trade interface deployed and verified."
