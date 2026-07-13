#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="/opt/sharipovai-repo"
PUBLIC_URL="https://85-137-88-17.sslip.io"

echo "[1/2] Running the protected SharipovAI deployment with Web2 ownership tests..."
cd "$ROOT"
bash scripts/deploy_market_paper_runtime.sh

echo "[2/2] Verifying the public page and browser guard..."
curl --fail --silent --show-error "$PUBLIC_URL/" | grep -F 'runtime_render_guard_v24.js?v=24' >/dev/null
curl --fail --silent --show-error "$PUBLIC_URL/static/web2/runtime_render_guard_v24.js?v=24" | grep -F "page === 'overview'" >/dev/null
curl --fail --silent --show-error "$PUBLIC_URL/health"
echo
echo "Web2 refresh ownership fix deployed and verified."
