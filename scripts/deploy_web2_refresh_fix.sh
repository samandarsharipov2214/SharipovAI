#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="/opt/sharipovai-repo"
PUBLIC_URL="https://85-137-88-17.sslip.io"
SERVICE="sharipovai"
ENV_FILE="$ROOT/deploy/vps/.env.vps"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "Missing $ENV_FILE" >&2
  exit 1
fi
python3 - "$ENV_FILE" "$PUBLIC_URL" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
public_url = sys.argv[2].rstrip("/")
lines = path.read_text(encoding="utf-8").splitlines()
updated = []
found = False
for line in lines:
    if line.startswith("WEBAPP_URL="):
        updated.append(f"WEBAPP_URL={public_url}")
        found = True
    else:
        updated.append(line)
if not found:
    updated.append(f"WEBAPP_URL={public_url}")
path.write_text("\n".join(updated) + "\n", encoding="utf-8")
print("TELEGRAM_WEBAPP_ENV_MIGRATED", public_url)
PY

echo "[1/3] Running the protected SharipovAI deployment with market intelligence tests..."
cd "$ROOT"
bash scripts/deploy_market_paper_runtime.sh

echo "[2/3] Verifying v34 TradingView height fix, v33 intelligence and public HTTPS health..."
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
grep -F -- "--tv32-widget-height" /app/dashboard/static/web2/tradingview_widget_height_fix_v34.css >/dev/null
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
grep -F "CANONICAL_WEBAPP_URL" /app/telegram_system_adapter.py >/dev/null
grep -F "_set_canonical_webapp_menu" /app/dashboard/telegram_webhook_api.py >/dev/null
! grep -F "onrender.com" /app/telegram_system_adapter.py >/dev/null || true
grep -F "no-store, no-cache, must-revalidate" /app/dashboard/web2_host.py >/dev/null
grep -F "Размер позиции" /app/dashboard/static/web2/overview_runtime_v25.js >/dev/null
grep -F "Результат движения цены" /app/dashboard/static/web2/overview_runtime_v25.js >/dev/null
grep -F "Комиссии" /app/dashboard/static/web2/overview_runtime_v25.js >/dev/null
grep -F "Чистый результат" /app/dashboard/static/web2/overview_runtime_v25.js >/dev/null
grep -F "цена справа является текущей, а не ценой выхода" /app/dashboard/static/web2/exchange_execution_settings_v18.js >/dev/null
grep -F "data-trade-filter" /app/dashboard/static/web2/exchange_execution_settings_v18.js >/dev/null
python -m py_compile /app/telegram_system_adapter.py /app/dashboard/market_intelligence_api.py /app/dashboard/web2_host.py /app/dashboard/currency_api.py /app/dashboard/trade_explanations.py /app/dashboard/paper_activity_api.py /app/dashboard/telegram_webhook_api.py /app/telegram_health.py
'
docker exec -e PYTHONPATH=/app "$SERVICE" python - <<'PY'
import asyncio
from dashboard.app import app
from market_paper_engine import PaperActivityEngine

routes = {getattr(route, "path", ""): route for route in app.routes}
for path in (
    "/api/learning-os/status", "/api/evidence-vault/recent", "/api/exchange/account/status",
    "/api/virtual-account/trades", "/api/currency/usd-rub", "/api/market-intelligence/snapshot",
    "/api/market-intelligence/replay", "/api/telegram/status", "/telegram/webhook",
):
    assert path in routes, f"missing source route: {path}"

trades_payload = routes["/api/virtual-account/trades"].endpoint()
assert trades_payload.get("status") == "ok" and isinstance(trades_payload.get("trades"), list)
for trade in trades_payload.get("trades", []):
    assert trade.get("entry_reason_ru")
    assert trade.get("operation_explanation_ru")
    assert float(trade.get("notional", 0) or 0) > 0
    assert float(trade.get("quantity", 0) or 0) > 0
print("TRANSPARENT_TRADE_CONTRACTS_OK")

snapshot = asyncio.run(routes["/api/market-intelligence/snapshot"].endpoint())
assert snapshot.get("status") in {"ok", "degraded"}
assert snapshot.get("real_orders_blocked") is True
print("MARKET_INTELLIGENCE_SNAPSHOT_OK", len(snapshot.get("rows", [])), len(snapshot.get("alerts", [])))

replay = asyncio.run(routes["/api/market-intelligence/replay"].endpoint(symbol="BTCUSDT", interval="15", limit=180))
assert replay.get("status") == "ok", replay.get("error")
assert replay.get("analysis_only") is True
assert replay.get("real_orders_placed") is False
assert replay.get("virtual_account_modified") is False
print("MARKET_REPLAY_OK", replay.get("candle_count"), replay.get("summary", {}).get("trade_count"))

state = PaperActivityEngine().state()
assert isinstance(state.get("trades"), list)
assert state.get("summary", {}).get("market_price_accounting") is True
assert state.get("summary", {}).get("real_orders_blocked") is True
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
curl --fail --silent --show-error "$PUBLIC_URL/health"
echo

echo "[3/3] Repairing and verifying Telegram webhook and Mini App menu..."
docker exec -e PYTHONPATH=/app -e EXPECTED_PUBLIC_URL="$PUBLIC_URL" "$SERVICE" python - <<'PY'
import os
import time
from dashboard.telegram_webhook_api import _set_webhook, _telegram
from telegram_health import telegram_health
from telegram_system_adapter import _webapp_url, main_keyboard

expected = os.environ["EXPECTED_PUBLIC_URL"].rstrip("/")
assert os.environ.get("BOT_TOKEN", "").strip(), "BOT_TOKEN is missing in deploy/vps/.env.vps"
assert os.environ.get("WEBAPP_URL", "").rstrip("/") == expected
assert _webapp_url() == expected
keyboard_url = main_keyboard()["inline_keyboard"][-1][0]["web_app"]["url"]
assert keyboard_url == expected, keyboard_url

result = _set_webhook()
assert result.get("status") == "ok", result

last = None
for _ in range(10):
    last = telegram_health()
    info = last.get("webhook_info", {}).get("result", {})
    menu = _telegram("getChatMenuButton").get("result", {})
    menu_url = ((menu.get("web_app") or {}).get("url") or "").rstrip("/")
    if last.get("verdict") == "working" and info.get("url") == f"{expected}/telegram/webhook" and not info.get("last_error_message") and menu.get("type") == "web_app" and menu_url == expected:
        print("TELEGRAM_WEBHOOK_OK", info.get("url"), "pending", info.get("pending_update_count", 0))
        print("TELEGRAM_MINIAPP_MENU_OK", menu_url)
        break
    time.sleep(2)
else:
    raise AssertionError({"health": last, "menu": _telegram("getChatMenuButton")})
PY

echo "Web2 v34, v33 intelligence, canonical Telegram Mini App and public health deployed and verified."
