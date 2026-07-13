#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="/opt/sharipovai-repo"
SERVICE="sharipovai"
ENV_FILE="$ROOT/deploy/vps/.env.vps"
LOCK_FILE="/run/sharipovai-telegram-deploy.lock"
POLL_SECONDS="5"

log() { printf '%s %s\n' "$(date -Is)" "$*"; }

read_request() {
  docker exec "$SERVICE" python - <<'PY'
import json
from pathlib import Path
path = Path('/var/lib/sharipovai/deployment_control/pending.json')
if not path.exists():
    raise SystemExit(3)
try:
    payload = json.loads(path.read_text(encoding='utf-8'))
except Exception:
    raise SystemExit(4)
required = {'request_id', 'action', 'actor_id', 'chat_id', 'created_at'}
if not isinstance(payload, dict) or not required.issubset(payload):
    raise SystemExit(5)
print(json.dumps(payload, separators=(',', ':')))
PY
}

write_status() {
  local state="$1" stage="$2" request_id="$3" chat_id="$4" message="${5:-}" commit="${6:-}"
  docker exec \
    -e DEPLOY_STATE="$state" \
    -e DEPLOY_STAGE="$stage" \
    -e DEPLOY_REQUEST_ID="$request_id" \
    -e DEPLOY_CHAT_ID="$chat_id" \
    -e DEPLOY_MESSAGE="$message" \
    -e DEPLOY_COMMIT="$commit" \
    "$SERVICE" python - <<'PY'
import json, os, time
from pathlib import Path
root = Path('/var/lib/sharipovai/deployment_control')
root.mkdir(parents=True, exist_ok=True)
path = root / 'status.json'
tmp = root / f'status.tmp-{os.getpid()}'
payload = {
    'state': os.environ['DEPLOY_STATE'],
    'stage': os.environ['DEPLOY_STAGE'],
    'request_id': os.environ['DEPLOY_REQUEST_ID'],
    'chat_id': int(os.environ['DEPLOY_CHAT_ID']),
    'message': os.environ.get('DEPLOY_MESSAGE', ''),
    'commit': os.environ.get('DEPLOY_COMMIT', ''),
    'updated_at': int(time.time()),
}
tmp.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True), encoding='utf-8')
os.replace(tmp, path)
PY
}

remove_request() {
  docker exec "$SERVICE" sh -lc 'rm -f /var/lib/sharipovai/deployment_control/pending.json'
}

read_env_value() {
  local name="$1"
  python3 - "$ENV_FILE" "$name" <<'PY'
import sys
path, name = sys.argv[1], sys.argv[2]
value = ''
try:
    lines = open(path, encoding='utf-8').read().splitlines()
except OSError:
    lines = []
for raw in lines:
    line = raw.strip()
    if not line or line.startswith('#') or '=' not in line:
        continue
    key, current = line.split('=', 1)
    if key.strip() == name:
        value = current.strip().strip('"').strip("'")
print(value)
PY
}

notify() {
  local chat_id="$1" text="$2"
  local token
  token="$(read_env_value BOT_TOKEN)"
  [[ -n "$token" ]] || return 0
  curl --fail --silent --show-error \
    --request POST "https://api.telegram.org/bot${token}/sendMessage" \
    --header 'Content-Type: application/json' \
    --data "$(python3 - "$chat_id" "$text" <<'PY'
import json, sys
print(json.dumps({'chat_id': int(sys.argv[1]), 'text': sys.argv[2], 'parse_mode': 'HTML'}))
PY
)" >/dev/null || true
}

process_request() {
  local request_json="$1"
  local request_id action actor_id chat_id created_at now commit output_file
  request_id="$(python3 -c 'import json,sys; print(json.load(sys.stdin)["request_id"])' <<<"$request_json")"
  action="$(python3 -c 'import json,sys; print(json.load(sys.stdin)["action"])' <<<"$request_json")"
  actor_id="$(python3 -c 'import json,sys; print(int(json.load(sys.stdin)["actor_id"]))' <<<"$request_json")"
  chat_id="$(python3 -c 'import json,sys; print(int(json.load(sys.stdin)["chat_id"]))' <<<"$request_json")"
  created_at="$(python3 -c 'import json,sys; print(int(json.load(sys.stdin)["created_at"]))' <<<"$request_json")"
  now="$(date +%s)"

  if [[ "$action" != "deploy_main" ]]; then
    write_status failed rejected "$request_id" "$chat_id" "Недопустимое действие" ""
    remove_request
    notify "$chat_id" "⛔ Обновление отклонено: недопустимое действие."
    return 0
  fi
  if (( now - created_at > 900 || created_at > now + 60 )); then
    write_status failed expired "$request_id" "$chat_id" "Запрос просрочен" ""
    remove_request
    notify "$chat_id" "⛔ Запрос обновления просрочен и был удалён."
    return 0
  fi

  write_status running "получение main" "$request_id" "$chat_id" "Запущено владельцем Telegram ${actor_id}" ""
  notify "$chat_id" "🔄 <b>Обновление SharipovAI началось</b>\n\nID: <code>${request_id}</code>\nСначала будут проверены кандидат и тесты."

  output_file="/tmp/${request_id}.log"
  if (
    cd "$ROOT"
    git fetch origin main
    git merge --ff-only origin/main
    commit="$(git rev-parse --short HEAD)"
    write_status running "защищённые тесты и deploy" "$request_id" "$chat_id" "Кандидат проверяется" "$commit"
    SHARIPOVAI_DEPLOY_WATCHER_ACTIVE=1 bash scripts/deploy_web2_refresh_fix.sh
  ) >"$output_file" 2>&1; then
    commit="$(cd "$ROOT" && git rev-parse --short HEAD)"
    write_status success completed "$request_id" "$chat_id" "Production проверен; реальные ордера заблокированы" "$commit"
    remove_request
    notify "$chat_id" "✅ <b>SharipovAI обновлён и проверен</b>\n\nКоммит: <code>${commit}</code>\nProduction healthy. Реальные ордера заблокированы."
    log "Deployment $request_id succeeded at $commit"
  else
    commit="$(cd "$ROOT" && git rev-parse --short HEAD 2>/dev/null || true)"
    local tail_text
    tail_text="$(tail -n 12 "$output_file" 2>/dev/null | sed 's/[<>]/ /g' | tail -c 2500)"
    write_status failed failed "$request_id" "$chat_id" "Deploy завершился ошибкой; production защищён откатом" "$commit"
    remove_request
    notify "$chat_id" "❌ <b>Обновление не выполнено</b>\n\nProduction сохранён или восстановлен.\nКоммит: <code>${commit:-—}</code>\n\n<pre>${tail_text}</pre>"
    log "Deployment $request_id failed; see $output_file"
  fi
}

log "SharipovAI Telegram deployment watcher started"
while true; do
  if docker container inspect "$SERVICE" >/dev/null 2>&1; then
    if request_json="$(read_request 2>/dev/null)"; then
      (
        flock -n 9 || exit 0
        process_request "$request_json"
      ) 9>"$LOCK_FILE"
    fi
  fi
  sleep "$POLL_SECONDS"
done
