#!/usr/bin/env bash
set -Eeuo pipefail
umask 077
# The checker atomically consumes one request in ProjectDatabase. This durable
# host claim also prevents repeated manual service starts from spending quota.
mkdir -p /root/sharipovai-model-continuation
exec 9>/run/lock/sharipovai-model-continuation.lock
flock -n 9 || exit 0
test ! -e /root/sharipovai-model-continuation/started || exit 0
docker exec sharipovai python -c 'from storage import ProjectDatabase; from learning_engine.forecast_readiness import NAMESPACE; s=ProjectDatabase().get_json(NAMESPACE,"state")["value"]; assert s["trigger_status"]=="requested_once" and s["last_result"]["ready"] is True'
date -u +%FT%TZ > /root/sharipovai-model-continuation/started
/root/.local/bin/codex exec --dangerously-bypass-approvals-and-sandbox -m gpt-6-astra - \
  < docs/paper-model-continuation.md \
  > /root/sharipovai-model-continuation/result.txt \
  2> /root/sharipovai-model-continuation/progress.log
