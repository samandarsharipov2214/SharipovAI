#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="/opt/sharipovai-repo"
PUBLIC_URL="https://85-137-88-17.sslip.io"
SERVICE="sharipovai"

echo "[1/2] Running the protected SharipovAI deployment with Web2 ownership tests..."
cd "$ROOT"
bash scripts/deploy_market_paper_runtime.sh

echo "[2/2] Verifying v32 TradingView market, transparent trades and public HTTPS health..."
docker exec "$SERVICE" sh -lc '
set -Eeuo pipefail
index=/app/dashboard/static/web2/index.html
grep -F "navigation_coordinator_v23.js?v=32" "$index" >/dev/null
grep -F "runtime_render_guard_v24.js?v=31" "$index" >/dev/null
grep -F "overview_runtime_v25.js?v=31" "$index" >/dev/null
grep -F "tradingview_market_v32.js?v=32" "$index" >/dev/null
grep -F "tradingview_market_v32.css?v=32" "$index" >/dev/null
grep -F "web2.js?v=29" "$index" >/dev/null
grep -F "system_status_v11.js?v=29" "$index" >/dev/null
grep -F "exchange_execution_settings_v18.js?v=30" "$index" >/dev/null
grep -F "interface_v30.css?v=30" "$index" >/dev/null
! grep -F "sections_v10.js" "$index" >/dev/null
! grep -F "market_terminal_v13.js" "$index" >/dev/null
! grep -F "market_terminal_v13.css" "$index" >/dev/null
grep -F "const VERSION = 32" /app/dashboard/static/web2/navigation_coordinator_v23.js >/dev/null
grep -F "['"'"'market'"'"', '"'"'tradingview_market_v32.js'"'"']" /app/dashboard/static/web2/navigation_coordinator_v23.js >/dev/null
grep -F "embed-widget-advanced-chart.js" /app/dashboard/static/web2/tradingview_market_v32.js >/dev/null
grep -F "embed-widget-technical-analysis.js" /app/dashboard/static/web2/tradingview_market_v32.js >/dev/null
grep -F "embed-widget-screener.js" /app/dashboard/static/web2/tradingview_market_v32.js >/dev/null
grep -F "embed-widget-crypto-coins-heatmap.js" /app/dashboard/static/web2/tradingview_market_v32.js >/dev/null
grep -F "embed-widget-market-overview.js" /app/dashboard/static/web2/tradingview_market_v32.js >/dev/null
grep -F "embed-widget-events.js" /app/dashboard/static/web2/tradingview_market_v32.js >/dev/null
grep -F "embed-widget-timeline.js" /app/dashboard/static/web2/tradingview_market_v32.js >/dev/null
grep -F "TradingView встроен как аналитический интерфейс" /app/dashboard/static/web2/tradingview_market_v32.js >/dev/null
grep -F "Реальная торговля остаётся заблокированной" /app/dashboard/static/web2/tradingview_market_v32.js >/dev/null
grep -F "/api/market/bybit-websocket/quote/" /app/dashboard/static/web2/tradingview_market_v32.js >/dev/null
grep -F "/api/market/orderbook/" /app/dashboard/static/web2/tradingview_market_v32.js >/dev/null
grep -F "/api/market/trades/" /app/dashboard/static/web2/tradingview_market_v32.js >/dev/null
grep -F "/api/virtual-account/state" /app/dashboard/static/web2/tradingview_market_v32.js >/dev/null
grep -F "no-store, no-cache, must-revalidate" /app/dashboard/web2_host.py >/dev/null
grep -F "Размер позиции" /app/dashboard/static/web2/overview_runtime_v25.js >/dev/null
grep -F "Результат движения цены" /app/dashboard/static/web2/overview_runtime_v25.js >/dev/null
grep -F "Комиссии" /app/dashboard/static/web2/overview_runtime_v25.js >/dev/null
grep -F "Чистый результат" /app/dashboard/static/web2/overview_runtime_v25.js >/dev/null
grep -F "цена справа является текущей, а не ценой выхода" /app/dashboard/static/web2/exchange_execution_settings_v18.js >/dev/null
grep -F "data-trade-filter" /app/dashboard/static/web2/exchange_execution_settings_v18.js >/dev/null
python -m py_compile /app/dashboard/web2_host.py /app/dashboard/currency_api.py /app/dashboard/trade_explanations.py /app/dashboard/paper_activity_api.py
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

trades_payload = routes["/api/virtual-account/trades"].endpoint()
assert trades_payload.get("status") == "ok" and isinstance(trades_payload.get("trades"), list)
for trade in trades_payload.get("trades", []):
    assert trade.get("entry_reason_ru"), f"missing entry explanation: {trade.get('id')}"
    assert trade.get("operation_explanation_ru"), f"missing operation explanation: {trade.get('id')}"
    assert float(trade.get("notional", 0) or 0) > 0, f"missing notional: {trade.get('id')}"
    assert float(trade.get("quantity", 0) or 0) > 0, f"missing quantity: {trade.get('id')}"
print("TRANSPARENT_TRADE_CONTRACTS_OK")

state = PaperActivityEngine().state()
assert isinstance(state.get("trades"), list), "virtual trade list missing"
assert state.get("summary", {}).get("market_price_accounting") is True, "market accounting not confirmed"
assert state.get("summary", {}).get("real_orders_blocked") is True, "real orders are not blocked"
print("WEB2_VIRTUAL_DATA_OK")
PY
headers="$(curl --fail --silent --show-error --head "$PUBLIC_URL/")"
grep -i -F "cache-control: no-store, no-cache, must-revalidate, max-age=0" <<<"$headers" >/dev/null
public_index="$(curl --fail --silent --show-error "$PUBLIC_URL/")"
grep -F "navigation_coordinator_v23.js?v=32" <<<"$public_index" >/dev/null
grep -F "overview_runtime_v25.js?v=31" <<<"$public_index" >/dev/null
grep -F "tradingview_market_v32.js?v=32" <<<"$public_index" >/dev/null
grep -F "tradingview_market_v32.css?v=32" <<<"$public_index" >/dev/null
! grep -F "market_terminal_v13.js" <<<"$public_index" >/dev/null
curl --fail --silent --show-error "$PUBLIC_URL/static/web2/tradingview_market_v32.js?v=32" | grep -F "embed-widget-advanced-chart.js" >/dev/null
curl --fail --silent --show-error "$PUBLIC_URL/health"
echo
echo "Web2 v32 TradingView market workspace deployed and verified."
