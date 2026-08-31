#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="${SHARIPOVAI_REPO_DIR:-/opt/sharipovai-repo}"
PUBLIC_URL="${SHARIPOVAI_PUBLIC_URL:-https://85-137-88-17.sslip.io}"
SERVICE="${SHARIPOVAI_SERVICE:-sharipovai}"

public_index_tmp="$(mktemp /tmp/sharipovai-public-index-XXXXXX.html)"
public_root_tmp="$(mktemp /tmp/sharipovai-public-root-XXXXXX.html)"
root_headers_tmp="$(mktemp /tmp/sharipovai-root-headers-XXXXXX.txt)"
static_headers_tmp="$(mktemp /tmp/sharipovai-static-headers-XXXXXX.txt)"
cleanup() {
  rm -f "$public_index_tmp" "$public_root_tmp" "$root_headers_tmp" "$static_headers_tmp"
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

echo "[verify 2/3] Verifying public Dashboard auth/static/health contracts..."
# The production root is intentionally authenticated. Anonymous public access
# must hit the fail-closed auth guard, not bypass it just to make deployment
# verification pass.
public_root_status="$(
  curl --connect-timeout 5 --max-time 15 --fail --silent --show-error \
    --dump-header "$root_headers_tmp" \
    --output "$public_root_tmp" \
    --write-out '%{http_code}' \
    "$PUBLIC_URL/"
)"
public_root_location="$(
  awk 'BEGIN { IGNORECASE=1 } /^location:/ { sub(/\r$/, ""); sub(/^[^:]+:[[:space:]]*/, ""); print; exit }' \
    "$root_headers_tmp"
)"
if [[ "$public_root_status" != "200" ]]; then
  echo "PUBLIC_SITE_V1_ENTRY_FAILED expected_status=200 actual_status=$public_root_status" >&2
  cat "$root_headers_tmp" >&2 || true
  exit 1
fi
echo "PUBLIC_SITE_V1_ENTRY_OK $public_root_status"
if ! grep -F '/static/site-v1/site.js' "$public_root_tmp" >/dev/null || ! grep -F 'SharipovAI' "$public_root_tmp" >/dev/null; then
  echo "PUBLIC_SITE_V1_ROOT_CONTENT_FAILED" >&2
  exit 1
fi
if ! awk 'BEGIN { IGNORECASE=1 } /^cache-control:/ { print tolower($0) }' "$root_headers_tmp" | grep -F 'no-store' >/dev/null; then
  echo "PUBLIC_SITE_V1_ROOT_CACHE_CONTROL_FAILED" >&2
  exit 1
fi
echo "PUBLIC_SITE_V1_ROOT_CONTRACT_OK"

# /static/ is the intentionally public asset surface. Verify the canonical
# Site V1 shell; the historical Web2 shell remains compatibility-only.
public_static_status="$(
  curl --connect-timeout 5 --max-time 15 --fail --silent --show-error \
    --dump-header "$static_headers_tmp" \
    --output "$public_index_tmp" \
    --write-out '%{http_code}' \
    "$PUBLIC_URL/static/site-v1/index.html"
)"
if [[ "$public_static_status" != "200" ]]; then
  echo "PUBLIC_SITE_V1_STATIC_HTTP_STATUS_FAILED expected=200 actual=$public_static_status" >&2
  cat "$static_headers_tmp" >&2 || true
  exit 1
fi
echo "PUBLIC_SITE_V1_STATIC_HTTP_STATUS_OK $public_static_status"
if ! grep -F '/static/site-v1/site.js' "$public_index_tmp" >/dev/null || ! grep -F 'SharipovAI' "$public_index_tmp" >/dev/null; then
  echo "PUBLIC_SITE_V1_ASSET_CONTRACT_FAILED" >&2
  exit 1
fi
echo "PUBLIC_SITE_V1_ASSET_CONTRACT_OK"

curl --connect-timeout 5 --max-time 15 --fail --silent --show-error "$PUBLIC_URL/health"
echo
curl --connect-timeout 5 --max-time 15 --fail --silent --show-error "$PUBLIC_URL/api/health"
echo

echo "[verify 3/3] Verifying Telegram webhook and Mini App menu..."
# A container cutover can produce one short-lived Telegram delivery error while
# Caddy swaps the upstream. Keep normal Telegram health conservative (300 s),
# but for this transactional cutover require a 30 s quiet period. Repeated real
# failures refresh last_error_date and therefore remain fail-closed. The longer
# polling window lets a single transient error age out without rolling back an
# otherwise healthy candidate.
docker exec -i \
  -e PYTHONPATH=/app \
  -e EXPECTED_PUBLIC_URL="$PUBLIC_URL" \
  -e TELEGRAM_WEBHOOK_ERROR_MAX_AGE_SECONDS=30 \
  "$SERVICE" python - <<'PY'
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

last_evidence = {}
for _ in range(30):
    health = telegram_health()
    info = health.get("webhook_info", {}).get("result", {})
    menu = _telegram("getChatMenuButton").get("result", {})
    menu_url = ((menu.get("web_app") or {}).get("url") or "").rstrip("/")
    pending_updates = int(info.get("pending_update_count") or 0)
    last_evidence = {
        "verdict": health.get("verdict"),
        "webhook_url": info.get("url"),
        "last_error_date": health.get("last_error_date"),
        "last_error_age_seconds": health.get("last_error_age_seconds"),
        "last_error_is_current": bool(health.get("last_error_is_current")),
        "stale_webhook_error_ignored": bool(health.get("stale_webhook_error_ignored")),
        "pending_update_count": pending_updates,
        "menu_type": menu.get("type"),
        "menu_url": menu_url,
    }
    if (
        health.get("verdict") == "working"
        and info.get("url") == f"{expected}/telegram/webhook"
        and not health.get("last_error_is_current")
        and pending_updates == 0
        and menu.get("type") == "web_app"
        and menu_url == expected
    ):
        if health.get("stale_webhook_error_ignored"):
            print("TELEGRAM_HISTORICAL_WEBHOOK_ERROR_IGNORED", health.get("last_error_date"))
        print("TELEGRAM_WEBHOOK_OK", info.get("url"))
        print("TELEGRAM_MINIAPP_MENU_OK", menu_url)
        break
    time.sleep(2)
else:
    raise AssertionError(f"Telegram webhook/menu verification failed: {last_evidence}")
PY

echo "WEB2_REFRESH_CONTRACTS_OK"
