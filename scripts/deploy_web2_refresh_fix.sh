#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="/opt/sharipovai-repo"
PUBLIC_URL="https://85-137-88-17.sslip.io"
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

echo "Running protected candidate deployment with transactional Web2/Telegram verification..."
cd "$ROOT"
SHARIPOVAI_DEPLOY_PROFILE=web2-refresh bash scripts/deploy_market_paper_runtime.sh

echo "Phase 7 Dashboard, public health and Telegram verified transactionally."
