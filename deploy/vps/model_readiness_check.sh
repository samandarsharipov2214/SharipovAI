#!/usr/bin/env bash
set -Eeuo pipefail
umask 077
exec 9>/run/lock/sharipovai-model-readiness.lock
flock -n 9 || exit 0
result=$(mktemp)
trap 'rm -f "$result"' EXIT
docker exec sharipovai python -m scripts.paper_forecast_readiness >"$result"
cat "$result"
if python3 -c 'import json,sys; sys.exit(json.load(open(sys.argv[1])).get("request_continuation") is not True)' "$result"; then
  systemctl start --no-block sharipovai-model-continuation.service
fi
