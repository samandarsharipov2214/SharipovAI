#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="/opt/sharipovai-repo"
PUBLIC_URL="https://85-137-88-17.sslip.io"
SERVICE="sharipovai"

echo "[1/2] Running the protected SharipovAI deployment with market intelligence tests..."
cd "$ROOT"
bash scripts/deploy_market_paper_runtime.sh

echo "[2/2] Verifying v34 TradingView height fix, v33 intelligence and public HTTPS health..."
docker exec "$SERVICE" sh -lc '
set -Eeuo pipefail
index=/app/dashboard/static/web2/index.html
grep -F "navigation_coordinator_v23.js?v=32" "$index" >/dev/null
grep -F "runtime_render_guard_v24.js?v=31" "$index" >/dev/null
grep -F "overview_runtime_v25.js?v=31" "$index" >/dev/null
grep -F "tradingview_market_v32.js?v=32" "$index" >/dev/null
grep -F "tradingview_market_v32.css?v=32" "$index" >/dev/null
grep -F "tradingview_widget_height_fix_v34.js?v=34" "$index" >/dev/null
grep -F "tradingview_widget_height_fix_v34.css?v=34" "$index" >/dev/null
grep -F "market_intelligence_v33.js?v=33" "$index" >/dev/null
grep -F "market_intelligence_v33.css?v=33" "$index" >/dev/null
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
grep -F "--tv32-widget-height" /app/dashboard/static/web2/tradingview_widget_height_fix_v34.css >/dev/null
grep -F "tradingview-widget-container__widget>iframe" /app/dashboard/static/web2/tradingview_widget_height_fix_v34.css >/dev/null
grep -F "frame.style.height = frameHeight" /app/dashboard/static/web2/tradingview_widget_height_fix_v34.js >/dev/null
grep -F "frame.setAttribute('"'"'height'"'"', String(widgetHeight))" /app/dashboard/static/web2/tradingview_widget_height_fix_v34.js >/dev/null
grep -F "/api/market-intelligence/snapshot" /app/dashboard/static/web2/market_intelligence_v33.js >/dev/null
grep -F "/api/market-intelligence/replay" /app/dashboard/static/web2/market_intelligence_v33.js >/dev/null
grep -F "Умный скринер" /app/dashboard/static/web2/market_intelligence_v33.js >/dev/null
grep -F "Оповещения" /app/dashboard/static/web2/market_intelligence_v33.js >/dev/null
grep -F "Replay Lab" /app/dashboard/static/web2/market_intelligence_v33.js >/dev/null
grep -F "не отправляет реальные ордера" /app/dashboard/static/web2/market_intelligence_v33.js >/dev/null
grep -F ".mi33-table" /app/dashboard/static/web2/market_intelligence_v33.css >/dev/null
grep -F "#mi33ReplayChart" /app/dashboard/static/web2/market_intelligence_v33.css >/dev/null
grep -F "install_market_intelligence_api(app)" /app/dashboard/paper_activity_api.py >/dev/null
grep -F "same_candle_conflict_policy" /app/dashboard/market_intelligence_api.py >/dev/null
grep -F "real_orders_placed" /app/dashboard/market_intelligence_api.py >/dev/null
grep -F "no-store, no-cache, must-revalidate" /app/dashboard/web2_host.py >/dev/null
grep -F "Размер позиции" /app/dashboard/static/web2/overview_runtime_v25.js >/dev/null
grep -F "Результат движения цены" /app/dashboard/static/web2/overview_runtime_v25.js >/dev/null
grep -F "Комиссии" /app/dashboard/static/web2/overview_runtime_v25.js >/dev/null
grep -F "Чистый результат" /app/dashboard/static/web2/overview_runtime_v25.js >/dev/null
grep -F "цена справа является текущей, а не ценой выхода" /app/dashboard/static/web2/exchange_execution_settings_v18.js >/dev/null
grep -F "data-trade-filter" /app/dashboard/static/web2/exchange_execution_settings_v18.js >/dev/null
python -m py_compile /app/dashboard/market_intelligence_api.py /app/dashboard/web2_host.py /app/dashboard/currency_api.py /app/dashboard/trade_explanations.py /app/dashboard/paper_activity_api.py
'
docker exec -e PYTHONPATH=/app "$SERVICE" python - <<'PY'
import asyncio

from dashboard.app import app
from market_paper_engine import PaperActivityEngine

routes = {getattr(route, "path", ""): route for route in app.routes}
for path in (
    "/api/learning-os/status",
    "/api/evidence-vault/recent",
    "/api/exchange/account/status",
    "/api/virtual-account/trades",
    "/api/currency/usd-rub",
    "/api/market-intelligence/snapshot",
    "/api/market-intelligence/replay",
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

snapshot = asyncio.run(routes["/api/market-intelligence/snapshot"].endpoint())
assert snapshot.get("status") in {"ok", "degraded"}
assert isinstance(snapshot.get("rows"), list)
assert isinstance(snapshot.get("alerts"), list)
assert snapshot.get("real_orders_blocked") is True
print("MARKET_INTELLIGENCE_SNAPSHOT_OK", len(snapshot.get("rows", [])), len(snapshot.get("alerts", [])))

replay = asyncio.run(routes["/api/market-intelligence/replay"].endpoint(symbol="BTCUSDT", interval="15", limit=180))
assert replay.get("status") == "ok", replay.get("error")
assert replay.get("analysis_only") is True
assert replay.get("real_orders_placed") is False
assert replay.get("virtual_account_modified") is False
assert isinstance(replay.get("trades"), list)
assert isinstance(replay.get("summary"), dict)
print("MARKET_REPLAY_OK", replay.get("candle_count"), replay.get("summary", {}).get("trade_count"))

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
grep -F "tradingview_widget_height_fix_v34.js?v=34" <<<"$public_index" >/dev/null
grep -F "tradingview_widget_height_fix_v34.css?v=34" <<<"$public_index" >/dev/null
grep -F "market_intelligence_v33.js?v=33" <<<"$public_index" >/dev/null
grep -F "market_intelligence_v33.css?v=33" <<<"$public_index" >/dev/null
! grep -F "market_terminal_v13.js" <<<"$public_index" >/dev/null
curl --fail --silent --show-error "$PUBLIC_URL/static/web2/tradingview_market_v32.js?v=32" | grep -F "embed-widget-advanced-chart.js" >/dev/null
curl --fail --silent --show-error "$PUBLIC_URL/static/web2/tradingview_widget_height_fix_v34.js?v=34" | grep -F "frame.style.height = frameHeight" >/dev/null
curl --fail --silent --show-error "$PUBLIC_URL/static/web2/tradingview_widget_height_fix_v34.css?v=34" | grep -F "tradingview-widget-container__widget>iframe" >/dev/null
curl --fail --silent --show-error "$PUBLIC_URL/static/web2/market_intelligence_v33.js?v=33" | grep -F "Replay Lab" >/dev/null
curl --fail --silent --show-error "$PUBLIC_URL/health"
echo
echo "Web2 v34 TradingView height fix, v33 intelligence and public health deployed and verified."
