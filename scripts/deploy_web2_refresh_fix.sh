#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="/opt/sharipovai-repo"
DEPLOY="$ROOT/deploy/vps"
SERVICE="sharipovai"
PUBLIC_URL="https://85-137-88-17.sslip.io"

cd "$DEPLOY"
echo "[1/3] Building candidate and testing Web2 page ownership..."
docker compose build "$SERVICE"
docker compose run --rm --no-deps \
  -e PAPER_ACTIVITY_AUTORUN_ENABLED=0 \
  --entrypoint sh "$SERVICE" -lc '
set -Eeuo pipefail
cd /app
python -m pytest tests/test_web2_page_ownership.py -q
'

echo "[2/3] Running the protected SharipovAI deployment..."
cd "$ROOT"
bash scripts/deploy_market_paper_runtime.sh

echo "[3/3] Verifying the public page and new browser guard..."
curl --fail --silent --show-error "$PUBLIC_URL/" | grep -F 'runtime_render_guard_v24.js?v=24' >/dev/null
curl --fail --silent --show-error "$PUBLIC_URL/static/web2/runtime_render_guard_v24.js?v=24" | grep -F "page === 'overview'" >/dev/null
curl --fail --silent --show-error "$PUBLIC_URL/health"
echo
echo "Web2 refresh ownership fix deployed and verified."
