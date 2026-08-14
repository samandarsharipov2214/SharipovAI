#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="/opt/sharipovai-repo"
PUBLIC_URL="https://85-137-88-17.sslip.io"
ENV_FILE="$ROOT/deploy/vps/.env.vps"

[[ -f "$ENV_FILE" ]] || { echo "Missing $ENV_FILE" >&2; exit 1; }

configured_url="$(python3 - "$ENV_FILE" <<'PY'
from pathlib import Path
import sys

for line in Path(sys.argv[1]).read_text(encoding="utf-8").splitlines():
    if line.startswith("WEBAPP_URL="):
        print(line.split("=", 1)[1].strip().strip('"').strip("'"))
        break
PY
)"
[[ "$configured_url" == "$PUBLIC_URL" ]] || {
  echo "WEBAPP_URL does not match the verified public endpoint; refusing to modify .env.vps." >&2
  exit 65
}
echo "TELEGRAM_WEBAPP_URL_VERIFIED $PUBLIC_URL"

echo "Running protected candidate deployment with transactional Web2/Telegram verification..."
cd "$ROOT"
SHARIPOVAI_DEPLOY_PROFILE=web2-refresh bash scripts/deploy_market_paper_runtime.sh

echo "Phase 7 Dashboard, public health and Telegram verified transactionally."
