#!/usr/bin/env bash
set -Eeuo pipefail

APP_DIR="${APP_DIR:-}"
HEALTH_URL="${HEALTH_URL:-http://127.0.0.1:8000/health}"

log() { printf '[repair-site] %s\n' "$*"; }
fail() { printf '[repair-site] ERROR: %s\n' "$*" >&2; exit 1; }

[[ ${EUID} -eq 0 ]] || fail 'run as root'

if [[ -z "${APP_DIR}" ]]; then
  for candidate in /opt/sharipovai-repo /opt/SharipovAI; do
    if [[ -d "${candidate}/.git" ]]; then
      APP_DIR="${candidate}"
      break
    fi
  done
fi

[[ -n "${APP_DIR}" && -d "${APP_DIR}/.git" ]] || fail 'SharipovAI repository was not found under /opt'
COMPOSE_DIR="${APP_DIR}/deploy/vps"
[[ -f "${COMPOSE_DIR}/docker-compose.yml" ]] || fail 'docker-compose.yml is missing'
[[ -f "${COMPOSE_DIR}/.env.vps" ]] || fail '.env.vps is missing'

cd "${COMPOSE_DIR}"

log 'current container state'
docker compose ps -a || true
log 'current application logs'
docker compose logs --tail=160 --no-color sharipovai || true

container_id="$(docker compose ps -a -q sharipovai 2>/dev/null || true)"
image_name='vps-sharipovai:latest'
volume_name=''
if [[ -n "${container_id}" ]]; then
  detected_image="$(docker inspect --format '{{.Config.Image}}' "${container_id}" 2>/dev/null || true)"
  [[ -n "${detected_image}" ]] && image_name="${detected_image}"
  volume_name="$(docker inspect --format '{{range .Mounts}}{{if eq .Destination "/var/lib/sharipovai"}}{{.Name}}{{end}}{{end}}' "${container_id}" 2>/dev/null || true)"
fi

if [[ -n "${volume_name}" ]]; then
  log "repairing persistent data permissions on volume ${volume_name}"
  docker run --rm --user 0 \
    -v "${volume_name}:/var/lib/sharipovai" \
    --entrypoint /bin/sh "${image_name}" \
    -c 'mkdir -p /var/lib/sharipovai && chown -R 10001:10001 /var/lib/sharipovai && chmod -R u+rwX /var/lib/sharipovai'
else
  log 'persistent data volume was not detected; continuing without changing storage'
fi

log 'starting application container only'
docker compose up -d --no-deps sharipovai

healthy=0
for attempt in $(seq 1 45); do
  if curl --fail --silent --show-error --max-time 4 "${HEALTH_URL}" >/dev/null 2>&1; then
    healthy=1
    break
  fi
  sleep 2
done

if [[ ${healthy} -ne 1 ]]; then
  log 'application is still unhealthy; exact runtime diagnostics follow'
  docker compose ps -a || true
  docker compose logs --tail=260 --no-color sharipovai || true
  if [[ -n "${container_id}" ]]; then
    docker inspect --format 'state={{.State.Status}} health={{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}} exit={{.State.ExitCode}} error={{.State.Error}}' "$(docker compose ps -a -q sharipovai)" 2>/dev/null || true
  fi
  fail 'application did not recover; use the printed traceback for the next code fix'
fi

log 'application health check passed; starting reverse proxy'
docker compose up -d caddy
curl --fail --silent --show-error --max-time 8 "${HEALTH_URL}" >/dev/null

log 'site recovered successfully'
docker compose ps
