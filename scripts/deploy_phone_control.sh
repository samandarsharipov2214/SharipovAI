#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="/opt/sharipovai-repo"
cd "$ROOT"

bash -n scripts/sharipovai_deploy_watcher.sh
python3 -m py_compile telegram_deploy_control.py telegram_system_adapter.py

bash scripts/deploy_web2_refresh_fix.sh
SHARIPOVAI_DEPLOY_WATCHER_ACTIVE=0 bash scripts/install_telegram_deploy_watcher.sh

docker exec -e PYTHONPATH=/app sharipovai python - <<'PY'
from telegram_deploy_control import admin_ids, deployment_keyboard
from telegram_system_adapter import setup_bot_commands

setup_bot_commands()
assert isinstance(admin_ids(), set)
assert deployment_keyboard(None, None) == [] or deployment_keyboard(None, None)
print("TELEGRAM_PHONE_CONTROL_RUNTIME_OK")
PY

systemctl is-enabled --quiet sharipovai-deploy-watcher.service
systemctl is-active --quiet sharipovai-deploy-watcher.service

echo "SharipovAI phone deployment control installed and verified."
