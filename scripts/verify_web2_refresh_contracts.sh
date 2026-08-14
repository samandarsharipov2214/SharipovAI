#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="${SHARIPOVAI_REPO_DIR:-/opt/sharipovai-repo}"
PUBLIC_URL="${SHARIPOVAI_PUBLIC_URL:-https://85-137-88-17.sslip.io}"
SERVICE="${SHARIPOVAI_SERVICE:-sharipovai}"

public_index_tmp="$(mktemp /tmp/sharipovai-public-index-XXXXXX.html)"
cleanup() {
  rm -f "$public_index_tmp"
}
trap cleanup EXIT

echo "[verify 1/3] Verifying current Dashboard asset and route contracts..."
docker exec -i "$SERVICE" python - <<'PY'
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit

root = Path("/app/dashboard/static/web2")
index = root / "index.html"
assert index.is_file() and index.stat().st_size > 0, "Web2 index.html missing"

class Assets(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.refs: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        value = values.get("src") if tag == "script" else values.get("href") if tag == "link" else None
        if value:
            path = urlsplit(value).path
            if path.startswith("/static/web2/"):
                self.refs.append(Path(path).name)

parser = Assets()
parser.feed(index.read_text(encoding="utf-8"))
refs = parser.refs
assert refs, "Web2 index has no local assets"

missing = sorted(name for name in refs if not (root / name).is_file() or (root / name).stat().st_size <= 0)
assert not missing, f"Web2 index references missing/empty assets: {missing}"

required = (
    ("navigation_coordinator_v", ".js"),
    ("runtime_render_guard_v", ".js"),
    ("tradingview_market_v", ".js"),
    ("market_intelligence_v", ".js"),
    ("campaign_operations_v", ".js"),
    ("campaign_decision_v", ".js"),
    ("campaign_monitor_v", ".js"),
    ("campaign_monitor_v", ".css"),
)
for prefix, suffix in required:
    assert any(name.startswith(prefix) and name.endswith(suffix) for name in refs), (
        f"required Web2 asset family missing from index: {prefix}*{suffix}"
    )

assert "market_terminal_v13.js" not in refs, "retired market_terminal_v13.js returned to index"

operations = next(name for name in refs if name.startswith("campaign_operations_v") and name.endswith(".js"))
monitor = next(name for name in refs if name.startswith("campaign_monitor_v") and name.endswith(".js"))
operations_text = (root / operations).read_text(encoding="utf-8")
monitor_text = (root / monitor).read_text(encoding="utf-8")
assert "/api/campaigns/operations" in operations_text
assert "/api/campaigns/phase7/monitor" in monitor_text
assert "phase7MonitorPanel" in monitor_text

print("WEB2_ASSET_CONTRACTS_OK", len(refs))
PY

docker exec -i -e PYTHONPATH=/app "$SERVICE" python - <<'PY'
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

echo "[verify 2/3] Verifying public Dashboard and health contracts..."
headers="$(curl --connect-timeout 5 --max-time 15 --fail --silent --show-error --head "$PUBLIC_URL/")"
grep -i -F "cache-control: no-store, no-cache, must-revalidate, max-age=0" <<<"$headers" >/dev/null
curl --connect-timeout 5 --max-time 15 --fail --silent --show-error "$PUBLIC_URL/" >"$public_index_tmp"
for family in \
  navigation_coordinator_v \
  runtime_render_guard_v \
  tradingview_market_v \
  market_intelligence_v \
  campaign_operations_v \
  campaign_decision_v \
  campaign_monitor_v; do
  grep -F "$family" "$public_index_tmp" >/dev/null
done
! grep -F "market_terminal_v13.js" "$public_index_tmp" >/dev/null
curl --connect-timeout 5 --max-time 15 --fail --silent --show-error "$PUBLIC_URL/health"
echo

echo "[verify 3/3] Verifying Telegram webhook and Mini App menu..."
docker exec -i -e PYTHONPATH=/app -e EXPECTED_PUBLIC_URL="$PUBLIC_URL" "$SERVICE" python - <<'PY'
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
    if (
        health.get("verdict") == "working"
        and info.get("url") == f"{expected}/telegram/webhook"
        and not info.get("last_error_message")
        and menu.get("type") == "web_app"
        and menu_url == expected
    ):
        print("TELEGRAM_WEBHOOK_OK", info.get("url"))
        print("TELEGRAM_MINIAPP_MENU_OK", menu_url)
        break
    time.sleep(2)
else:
    raise AssertionError("Telegram webhook/menu verification failed")
PY

echo "WEB2_REFRESH_CONTRACTS_OK"
