#!/usr/bin/env bash
# Verify that an approved manifest is backed by the canonical owner/security decision.

# Capability-dropped application containers cannot use UID 0 as a privileged
# bypass. Rewrite legacy helper invocations to the canonical application UID.
docker() {
    local -a arguments=()
    while [ "$#" -gt 0 ]; do
        if [ "$1" = "--user" ] && [ "${2:-}" = "0" ]; then
            arguments+=("--user" "${CONTAINER_USER:-10001:10001}")
            shift 2
        else
            arguments+=("$1")
            shift
        fi
    done
    command docker "${arguments[@]}"
}

claim_approved_patch() {
    if ! container_running sharipovai; then
        log "Cannot claim approved patch while sharipovai is stopped."
        return 1
    fi
    case "$AGENT_DECISIONS_ENDPOINT" in
        http://127.0.0.1:*/*|http://localhost:*/*) ;;
        *)
            log "Refusing non-loopback agent_decisions endpoint: $AGENT_DECISIONS_ENDPOINT"
            return 1
            ;;
    esac

    docker exec -i --user "${CONTAINER_USER:-10001:10001}" \
        -e SELF_HEALING_APPROVED_MANIFEST_PATH="$APPROVED_MANIFEST_PATH" \
        -e SELF_HEALING_AGENT_DECISIONS_ENDPOINT="$AGENT_DECISIONS_ENDPOINT/claim" \
        sharipovai python - <<'PY_APPROVED_CLAIM'
import json
import os
import re
from pathlib import PurePosixPath
from urllib import request

manifest_path = os.environ["SELF_HEALING_APPROVED_MANIFEST_PATH"]
with open(manifest_path, "r", encoding="utf-8") as handle:
    payload = json.load(handle)
required = {"decision_id", "base_sha", "patch_sha256", "patch_container_path"}
if not isinstance(payload, dict) or set(payload) != required:
    raise SystemExit("approved manifest must contain exactly the required fields")
decision_id = str(payload["decision_id"])
base_sha = str(payload["base_sha"]).lower()
patch_sha = str(payload["patch_sha256"]).lower()
patch_path = str(payload["patch_container_path"])
if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,169}", decision_id):
    raise SystemExit("invalid decision_id")
if not re.fullmatch(r"[0-9a-f]{40}", base_sha):
    raise SystemExit("invalid base_sha")
if not re.fullmatch(r"[0-9a-f]{64}", patch_sha):
    raise SystemExit("invalid patch_sha256")
if not re.fullmatch(r"/var/lib/sharipovai/\.self_healing/[A-Za-z0-9._/-]+", patch_path):
    raise SystemExit("patch_container_path is outside the self-healing runtime directory")
path = PurePosixPath(patch_path)
if any(part in {"", ".", ".."} for part in path.parts) or path.as_posix() != patch_path:
    raise SystemExit("patch_container_path is not normalized")

token = os.environ.get("SHARIPOVAI_SERVICE_TOKEN", "").strip()
if not token:
    raise SystemExit("SHARIPOVAI_SERVICE_TOKEN is not configured")
claim = {
    "decision_id": decision_id,
    "action": "apply_approved_patch",
    "base_sha": base_sha,
    "patch_sha256": patch_sha,
}
req = request.Request(
    os.environ["SELF_HEALING_AGENT_DECISIONS_ENDPOINT"],
    data=json.dumps(claim, separators=(",", ":")).encode("utf-8"),
    headers={
        "Content-Type": "application/json",
        "X-SharipovAI-Service-Token": token,
    },
    method="POST",
)
with request.urlopen(req, timeout=10) as response:
    if response.status != 200:
        raise SystemExit(f"agent_decisions claim returned HTTP {response.status}")
    result = json.loads(response.read().decode("utf-8"))
if result.get("status") != "ok" or result.get("approved") is not True:
    raise SystemExit(f"agent_decisions claim rejected manifest: {result!r}")
PY_APPROVED_CLAIM
}
