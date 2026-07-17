#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="/opt/sharipovai-repo"
PUBLIC_URL="https://85-137-88-17.sslip.io"
SERVICE="sharipovai"
ENV_FILE="$ROOT/deploy/vps/.env.vps"

[[ -f "$ENV_FILE" ]] || { echo "Missing $ENV_FILE" >&2; exit 1; }

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

echo "[1/3] Running protected candidate deployment..."
cd "$ROOT"
bash scripts/deploy_market_paper_runtime.sh

echo "[2/3] Verifying current Dashboard and public health contracts..."
docker exec "$SERVICE" sh -lc '
set -Eeuo pipefail
root=/app/dashboard/static/web2
index=$root/index.html
for asset in \
  navigation_coordinator_v23.js \
  runtime_render_guard_v24.js \
  tradingview_market_v32.js \
  market_intelligence_v33.js \
  campaign_operations_v36.js \
  campaign_decision_v37.js \
  campaign_monitor_v38.js \
  campaign_monitor_v38.css; do
  test -s "$root/$asset"
  grep -F "$asset" "$index" >/dev/null
done
! grep -F "market_terminal_v13.js" "$index" >/dev/null
grep -F "/api/campaigns/operations" "$root/campaign_operations_v36.js" >/dev/null
grep -F "/api/campaigns/phase7/monitor" "$root/campaign_monitor_v38.js" >/dev/null
grep -F "phase7MonitorPanel" "$root/campaign_monitor_v38.js" >/dev/null
python -m py_compile /app/dashboard/phase7_campaign_api.py /app/campaigns/phase7_monitor.py
'

docker exec -e PYTHONPATH=/app "$SERVICE" python - <<'PY'
from dashboard.app import app
routes = {getattr(route, "path", "") for route in app.routes}
required = {
    "/health",
    "/api/campaigns/operations",
    "/api/campaigns/phase7/monitor",
    "/api/campaigns/phase7/fills",
    "/api/campaigns/phase7/report",
    "/api/telegram/status",
    "/telegram/webhook",
}
missing = sorted(required - routes)
assert not missing, f"missing runtime routes: {missing}"
print("PHASE7_DASHBOARD_CONTRACTS_OK", len(required))
PY

headers="$(curl --fail --silent --show-error --head "$PUBLIC_URL/")"
grep -i -F "cache-control: no-store, no-cache, must-revalidate, max-age=0" <<<"$headers" >/dev/null
public_index="$(curl --fail --silent --show-error "$PUBLIC_URL/")"
for asset in campaign_operations_v36.js campaign_decision_v37.js campaign_monitor_v38.js campaign_monitor_v38.css; do
  grep -F "$asset" <<<"$public_index" >/dev/null
done
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
assert os.environ.get("BOT_TOKEN", "").strip()
assert os.environ.get("WEBAPP_URL", "").rstrip("/") == expected
assert _webapp_url() == expected
assert main_keyboard()["inline_keyboard"][-1][0]["web_app"]["url"] == expected
assert _set_webhook().get("status") == "ok"

for _ in range(10):
    health = telegram_health()
    info = health.get("webhook_info", {}).get("result", {})
    menu = _telegram("getChatMenuButton").get("result", {})
    menu_url = ((menu.get("web_app") or {}).get("url") or "").rstrip("/")
    if health.get("verdict") == "working" and info.get("url") == f"{expected}/telegram/webhook" and not info.get("last_error_message") and menu.get("type") == "web_app" and menu_url == expected:
        print("TELEGRAM_WEBHOOK_OK", info.get("url"))
        print("TELEGRAM_MINIAPP_MENU_OK", menu_url)
        break
    time.sleep(2)
else:
    raise AssertionError("Telegram webhook/menu verification failed")
PY

echo "Phase 7 Dashboard, public health and Telegram verified."
