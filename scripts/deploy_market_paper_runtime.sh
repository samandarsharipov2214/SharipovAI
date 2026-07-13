#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="/opt/sharipovai-repo"
DEPLOY="$ROOT/deploy/vps"
SERVICE="sharipovai"
ROLLBACK_TAG="sharipovai-market-paper-rollback:latest"

cd "$DEPLOY"
old_image_id="$(docker inspect -f '{{.Image}}' "$SERVICE" 2>/dev/null || true)"
old_image_ref="$(docker inspect -f '{{.Config.Image}}' "$SERVICE" 2>/dev/null || true)"
if [[ -n "$old_image_id" ]]; then
  docker tag "$old_image_id" "$ROLLBACK_TAG"
fi

rollback() {
  if [[ -n "$old_image_ref" ]] && docker image inspect "$ROLLBACK_TAG" >/dev/null 2>&1; then
    echo "New runtime verification failed; restoring previous SharipovAI image."
    docker tag "$ROLLBACK_TAG" "$old_image_ref"
    docker compose up -d --force-recreate "$SERVICE"
  fi
}
trap rollback ERR

docker compose build "$SERVICE"
docker compose run --rm --no-deps "$SERVICE" \
  python -m pytest tests/test_market_paper_engine.py -q
docker compose up -d --force-recreate "$SERVICE"

for _ in $(seq 1 40); do
  health="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$SERVICE" 2>/dev/null || true)"
  if [[ "$health" == "healthy" ]]; then
    break
  fi
  sleep 2
done

health="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$SERVICE")"
if [[ "$health" != "healthy" ]]; then
  echo "SharipovAI health check failed: $health" >&2
  exit 1
fi

docker exec "$SERVICE" python -m py_compile \
  /app/market_paper_engine.py \
  /app/paper_activity_autorun.py \
  /app/dashboard/paper_activity_api.py \
  /app/dashboard/realtime_status_api.py
docker exec "$SERVICE" python /app/scripts/verify_market_paper_runtime.py

trap - ERR
echo "Market-backed virtual account deployed and verified."
echo "Real exchange orders remain blocked."
