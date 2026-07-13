#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="/opt/sharipovai-repo"
PUBLIC_URL="https://85-137-88-17.sslip.io"

echo "[1/2] Running the protected SharipovAI deployment with Web2 ownership tests..."
cd "$ROOT"
bash scripts/deploy_market_paper_runtime.sh

echo "[2/2] Verifying public v25 pages, assets and virtual-account data..."
index="$(curl --fail --silent --show-error "$PUBLIC_URL/")"
grep -F 'navigation_coordinator_v23.js?v=25' <<<"$index" >/dev/null
grep -F 'web2.js?v=25' <<<"$index" >/dev/null
grep -F 'overview_runtime_v25.js?v=25' <<<"$index" >/dev/null
grep -F 'learning_runtime_v25.js?v=25' <<<"$index" >/dev/null
grep -F 'exchange_execution_settings_v18.js?v=25' <<<"$index" >/dev/null

curl --fail --silent --show-error "$PUBLIC_URL/static/web2/web2.js?v=25" | grep -F 'function renderChat()' >/dev/null
curl --fail --silent --show-error "$PUBLIC_URL/static/web2/overview_runtime_v25.js?v=25" | grep -F '/api/virtual-account/state' >/dev/null
curl --fail --silent --show-error "$PUBLIC_URL/static/web2/learning_runtime_v25.js?v=25" | grep -F '/api/virtual-account/trades' >/dev/null
curl --fail --silent --show-error "$PUBLIC_URL/api/virtual-account/trades" | grep -F '"trades"' >/dev/null
curl --fail --silent --show-error "$PUBLIC_URL/health"
echo
echo "Web2 v25 single-owner interface deployed and verified."
