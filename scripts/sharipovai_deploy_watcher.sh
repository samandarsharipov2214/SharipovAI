#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="/opt/sharipovai-repo"
SERVICE="sharipovai"
ENV_FILE="$ROOT/deploy/vps/.env.vps"
LOCK_FILE="/run/sharipovai-telegram-deploy.lock"
POLL_SECONDS="5"
FETCH_REMOTE="${FETCH_REMOTE:-origin}"
STATUS_WRITE_TIMEOUT_SECONDS="${SHARIPOVAI_DEPLOY_STATUS_WRITE_TIMEOUT_SECONDS:-20}"
DEPLOY_TIMEOUT_SECONDS="${SHARIPOVAI_DEPLOY_TIMEOUT_SECONDS:-1800}"
DEPLOY_HEARTBEAT_SECONDS="${SHARIPOVAI_DEPLOY_HEARTBEAT_SECONDS:-30}"
DEPLOY_KILL_AFTER_SECONDS="${SHARIPOVAI_DEPLOY_KILL_AFTER_SECONDS:-30}"

log() { printf '%s %s\n' "$(date -Is)" "$*"; }

for limit in "$STATUS_WRITE_TIMEOUT_SECONDS" "$DEPLOY_TIMEOUT_SECONDS" "$DEPLOY_HEARTBEAT_SECONDS" "$DEPLOY_KILL_AFTER_SECONDS"; do
  [[ "$limit" =~ ^[1-9][0-9]*$ ]] || { echo "Deploy timeout values must be positive integers" >&2; exit 64; }
done

if [[ "${FETCH_REMOTE}" == https://github.com/* ]]; then
  [[ "${FETCH_REMOTE}" =~ ^https://github\.com/[A-Za-z0-9._-]+/[A-Za-z0-9._-]+(\.git)?$ ]] || {
    echo 'FETCH_REMOTE must be a plain HTTPS GitHub repository URL' >&2
    exit 1
  }
else
  [[ "${FETCH_REMOTE}" =~ ^[A-Za-z0-9._-]+$ ]] || {
    echo 'FETCH_REMOTE contains unsafe characters' >&2
    exit 1
  }
fi

read_request() {
  timeout --foreground --kill-after=5s "$STATUS_WRITE_TIMEOUT_SECONDS" docker exec -i "$SERVICE" python - <<'PY'
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

validate_owner_request() {
  local request_json="$1" verdict
  verdict="$(timeout --foreground --kill-after=5s "$STATUS_WRITE_TIMEOUT_SECONDS" docker exec -i \
    -e DEPLOY_REQUEST_JSON="$request_json" \
    "$SERVICE" python -c '
import json
import os
from pathlib import Path

def positive_int(value):
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else None

def nonzero_int(value):
    return value if isinstance(value, int) and not isinstance(value, bool) and value != 0 else None

try:
    request = json.loads(os.environ["DEPLOY_REQUEST_JSON"])
    owner = json.loads((Path("/var/lib/sharipovai/deployment_control") / "owner.json").read_text(encoding="utf-8"))
except (KeyError, OSError, UnicodeDecodeError, ValueError, json.JSONDecodeError):
    raise SystemExit(1)

if not isinstance(request, dict) or not isinstance(owner, dict):
    raise SystemExit(1)
if not isinstance(request.get("request_id"), str) or not request["request_id"]:
    raise SystemExit(1)
if not isinstance(request.get("action"), str) or not request["action"]:
    raise SystemExit(1)
if positive_int(request.get("created_at")) is None:
    raise SystemExit(1)
owner_user = positive_int(owner.get("user_id"))
owner_chat = nonzero_int(owner.get("chat_id"))
actor = positive_int(request.get("actor_id"))
chat = nonzero_int(request.get("chat_id"))
if None in (owner_user, owner_chat, actor, chat) or actor != owner_user or chat != owner_chat:
    raise SystemExit(1)
print("authorized")
' 2>/dev/null)" || return 1
  [[ "$verdict" == "authorized" ]]
}

write_status() {
  local state="$1" stage="$2" request_id="$3" chat_id="$4" message="${5:-}" commit="${6:-}"
  timeout --foreground --kill-after=5s "$STATUS_WRITE_TIMEOUT_SECONDS" docker exec -i \
    -e DEPLOY_STATE="$state" \
    -e DEPLOY_STAGE="$stage" \
    -e DEPLOY_REQUEST_ID="$request_id" \
    -e DEPLOY_CHAT_ID="$chat_id" \
    -e DEPLOY_MESSAGE="$message" \
    -e DEPLOY_COMMIT="$commit" \
    -e DEPLOY_WATCHER_PID="$$" \
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
    'watcher_pid': int(os.environ.get('DEPLOY_WATCHER_PID', '0') or 0),
    'updated_at': int(time.time()),
    'heartbeat_at': int(time.time()),
}
tmp.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True), encoding='utf-8')
os.replace(tmp, path)
PY
}

remove_request() {
  timeout --foreground --kill-after=5s "$STATUS_WRITE_TIMEOUT_SECONDS" \
    docker exec "$SERVICE" sh -lc 'rm -f /var/lib/sharipovai/deployment_control/pending.json'
}

publish_status() {
  if ! write_status "$@"; then
    log "Unable to persist deploy status; deployment will not continue."
    return 1
  fi
}

heartbeat_loop() {
  local request_id="$1" chat_id="$2" commit="$3"
  while sleep "$DEPLOY_HEARTBEAT_SECONDS"; do
    publish_status running "защищённые тесты и deploy" "$request_id" "$chat_id" \
      "Кандидат проверяется" "$commit" || log "Deploy heartbeat persistence failed"
  done
}

run_deploy_with_watchdog() {
  local request_id="$1" chat_id="$2" commit="$3" heartbeat_pid result
  heartbeat_loop "$request_id" "$chat_id" "$commit" &
  heartbeat_pid=$!
  set +e
  timeout --signal=TERM --kill-after="${DEPLOY_KILL_AFTER_SECONDS}s" \
    "${DEPLOY_TIMEOUT_SECONDS}s" \
    env SHARIPOVAI_DEPLOY_WATCHER_ACTIVE=1 \
    bash "$ROOT/scripts/deploy_web2_refresh_fix.sh"
  result=$?
  set -e
  kill "$heartbeat_pid" 2>/dev/null || true
  wait "$heartbeat_pid" 2>/dev/null || true
  return "$result"
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

fetch_main() {
  local target_sha
  cd "$ROOT"
  if [[ "${FETCH_REMOTE}" == https://github.com/* ]]; then
    git fetch --no-tags "${FETCH_REMOTE}" main
    target_sha="$(git rev-parse FETCH_HEAD)"
    git checkout -q main
    git reset --hard "${target_sha}"
  else
    git fetch --prune "${FETCH_REMOTE}" main
    git merge --ff-only "${FETCH_REMOTE}/main"
  fi
}

run_deploy_request_with_private_output() (
  local request_id="$1" chat_id="$2"
  local commit deploy_result output_file tail_text tmp_root

  tmp_root="${TMPDIR:-/tmp}"
  if [[ "$tmp_root" != /* || ! -d "$tmp_root" ]]; then
    publish_status failed failed "$request_id" "$chat_id" \
      "Не удалось создать защищённый журнал deploy; production не изменён" "" || true
    remove_request || true
    notify "$chat_id" "❌ <b>Обновление не выполнено</b>\n\nЗащищённый временный журнал недоступен. Production не изменён."
    log "Deployment $request_id stopped because the private temporary directory is unavailable"
    return 0
  fi
  if ! output_file="$(umask 077; mktemp "${tmp_root%/}/sharipovai-deploy.XXXXXXXXXX.log")"; then
    publish_status failed failed "$request_id" "$chat_id" \
      "Не удалось создать защищённый журнал deploy; production не изменён" "" || true
    remove_request || true
    notify "$chat_id" "❌ <b>Обновление не выполнено</b>\n\nЗащищённый временный журнал недоступен. Production не изменён."
    log "Deployment $request_id stopped because private temporary-file creation failed"
    return 0
  fi
  trap 'rm -f -- "$output_file"' EXIT
  if [[ ! -f "$output_file" || -L "$output_file" || "$(stat -c '%a' "$output_file" 2>/dev/null)" != "600" ]]; then
    publish_status failed failed "$request_id" "$chat_id" \
      "Защищённый журнал deploy не прошёл проверку; production не изменён" "" || true
    remove_request || true
    notify "$chat_id" "❌ <b>Обновление не выполнено</b>\n\nВременный журнал не прошёл security-проверку. Production не изменён."
    log "Deployment $request_id stopped because the private temporary file failed validation"
    return 0
  fi

  if ! fetch_main >"$output_file" 2>&1; then
    commit="$(git -C "$ROOT" rev-parse --short HEAD 2>/dev/null || true)"
    publish_status failed failed "$request_id" "$chat_id" "Не удалось получить проверенный main; production не изменён" "$commit" || true
    remove_request || true
    log "Deployment $request_id could not fetch main; private temporary output removed"
    return 0
  fi
  commit="$(git -C "$ROOT" rev-parse --short HEAD)"
  if ! publish_status running "защищённые тесты и deploy" "$request_id" "$chat_id" "Кандидат проверяется" "$commit"; then
    return 1
  fi

  if run_deploy_with_watchdog "$request_id" "$chat_id" "$commit" >>"$output_file" 2>&1; then
    commit="$(git -C "$ROOT" rev-parse --short HEAD)"
    publish_status success completed "$request_id" "$chat_id" "Production проверен; реальные ордера заблокированы" "$commit" || true
    remove_request || true
    notify "$chat_id" "✅ <b>SharipovAI обновлён и проверен</b>\n\nКоммит: <code>${commit}</code>\nProduction healthy. Реальные ордера заблокированы."
    log "Deployment $request_id succeeded at $commit; private temporary output removed"
  else
    deploy_result=$?
    commit="$(git -C "$ROOT" rev-parse --short HEAD 2>/dev/null || true)"
    tail_text="$(tail -n 12 "$output_file" 2>/dev/null | sed 's/[<>]/ /g' | tail -c 2500)"
    if [[ "$deploy_result" == "124" || "$deploy_result" == "137" ]]; then
      publish_status timeout timed_out "$request_id" "$chat_id" "Deploy превысил лимит времени; production защищён откатом" "$commit" || true
      notify "$chat_id" "⏱️ <b>Обновление остановлено по таймауту</b>\n\nProduction сохранён или восстановлен.\nКоммит: <code>${commit:-—}</code>"
      log "Deployment $request_id timed out; private temporary output removed after terminal evidence"
    else
      publish_status failed failed "$request_id" "$chat_id" "Deploy завершился ошибкой; production защищён откатом" "$commit" || true
      notify "$chat_id" "❌ <b>Обновление не выполнено</b>\n\nProduction сохранён или восстановлен.\nКоммит: <code>${commit:-—}</code>\n\n<pre>${tail_text}</pre>"
      log "Deployment $request_id failed; private temporary output removed after terminal evidence"
    fi
    remove_request || true
  fi
)

process_request() {
  local request_json="$1"
  local request_id action actor_id chat_id created_at now
  if ! validate_owner_request "$request_json"; then
    write_status failed security_blocked "blocked-untrusted-request" 0 "Запрос отклонён независимой host-проверкой владельца" ""
    remove_request
    log "Deployment request rejected by independent host owner validation"
    return 0
  fi
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

  if ! publish_status running "получение main" "$request_id" "$chat_id" "Запущено владельцем Telegram ${actor_id}" ""; then
    return 1
  fi
  notify "$chat_id" "🔄 <b>Обновление SharipovAI началось</b>\n\nID: <code>${request_id}</code>\nСначала будут проверены кандидат и тесты."
  run_deploy_request_with_private_output "$request_id" "$chat_id"
}

main() {
  log "SharipovAI Telegram deployment watcher started"
  while true; do
    if docker container inspect "$SERVICE" >/dev/null 2>&1; then
      if request_json="$(read_request 2>/dev/null)"; then
        (
          flock -n 9 || exit 0
          process_request "$request_json" || log "Deployment request processing stopped before execution"
        ) 9>"$LOCK_FILE"
      fi
    fi
    sleep "$POLL_SECONDS"
  done
}

if [[ "${SHARIPOVAI_DEPLOY_WATCHER_LIBRARY:-0}" != "1" ]]; then
  main
fi
