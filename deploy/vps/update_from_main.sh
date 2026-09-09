#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

APP_DIR="${APP_DIR:-/opt/sharipovai-repo}"
BRANCH="${BRANCH:-main}"
FETCH_REMOTE="${FETCH_REMOTE:-origin}"
LOCK_FILE="${LOCK_FILE:-/run/lock/sharipovai-deploy.lock}"
HEALTH_URL="${HEALTH_URL:-http://127.0.0.1:8000/health}"
HEALTH_TIMEOUT_SECONDS="${HEALTH_TIMEOUT_SECONDS:-360}"
HEALTH_DELAY_SECONDS="${HEALTH_DELAY_SECONDS:-2}"
EXPECTED_TARGET_SHA="${SHARIPOVAI_EXPECTED_TARGET_SHA:-}"

log() { printf '[sharipovai-update] %s\n' "$*"; }
fail() { printf '[sharipovai-update] ERROR: %s\n' "$*" >&2; exit 1; }

[[ ${EUID} -eq 0 ]] || fail 'run as root'
[[ "${APP_DIR}" == /* ]] || fail 'APP_DIR must be an absolute path'
[[ "${BRANCH}" =~ ^[A-Za-z0-9._/-]+$ ]] || fail 'BRANCH contains unsafe characters'
[[ -d "${APP_DIR}/.git" ]] || fail "git repository not found at ${APP_DIR}"
[[ -f "${APP_DIR}/deploy/vps/.env.vps" ]] || fail 'deploy/vps/.env.vps is missing'

if [[ "${FETCH_REMOTE}" == https://github.com/* ]]; then
  [[ "${FETCH_REMOTE}" =~ ^https://github\.com/[A-Za-z0-9._-]+/[A-Za-z0-9._-]+(\.git)?$ ]] \
    || fail 'FETCH_REMOTE must be a plain HTTPS GitHub repository URL'
else
  [[ "${FETCH_REMOTE}" =~ ^[A-Za-z0-9._-]+$ ]] || fail 'FETCH_REMOTE contains unsafe characters'
fi

install -d -m 0755 "$(dirname "${LOCK_FILE}")"
exec 9>"${LOCK_FILE}"
flock -n 9 || fail 'another SharipovAI update is already running'

previous_sha="$(git -C "${APP_DIR}" rev-parse HEAD)"
[[ -z "$(git -C "${APP_DIR}" status --porcelain --untracked-files=normal)" ]] || fail 'production checkout is not clean'
compose_dir="${APP_DIR}/deploy/vps"
rollback_started=0
backup_exporter_tmp=""
preflight_tmp=""
target_compose_tmp=""
rendered_config=""
context_helper=""
runtime_override=""
verified_override=""

cleanup() {
  rm -f \
    "${backup_exporter_tmp:-}" \
    "${preflight_tmp:-}" \
    "${target_compose_tmp:-}" \
    "${rendered_config:-}" \
    "${context_helper:-}" \
    "${runtime_override:-}" \
    "${verified_override:-}"
}
trap cleanup EXIT

health_check() {
  # Keep this probe in the parsed function: checkout reset during rollback must
  # not replace it with an older, shorter readiness contract.
  python3 - "${HEALTH_URL}" "${HEALTH_TIMEOUT_SECONDS}" "${HEALTH_DELAY_SECONDS}" <<'HEALTH_PY'
import math
import subprocess
import sys
import time


def check_health(url, timeout_seconds, delay_seconds):
    if not (math.isfinite(timeout_seconds) and 1 <= timeout_seconds <= 3600
            and math.isfinite(delay_seconds) and 0 < delay_seconds <= 30):
        raise ValueError("health deadline/delay outside bounded range")
    started = time.monotonic()
    deadline = started + timeout_seconds
    last_state = "unavailable"
    last_probe = "not_started"
    attempts = 0

    def probe(command):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("startup deadline reached")
        return subprocess.run(command, capture_output=False, stdout=subprocess.PIPE,
                              stderr=subprocess.DEVNULL, text=True, check=False,
                              timeout=min(5.0, remaining))

    while time.monotonic() < deadline:
        attempts += 1
        try:
            result = probe([
                "docker", "inspect", "--format",
                "{{.State.Status}} {{if .State.Health}}{{.State.Health.Status}}{{else}}missing{{end}} "
                "{{.RestartCount}} {{.State.ExitCode}} {{.State.OOMKilled}}", "sharipovai",
            ])
            last_probe = "docker_failed"
            if result.returncode == 0:
                state, health, restarts, exit_code, oom = result.stdout.strip().split()
                if (state not in {"running", "restarting", "exited", "created", "paused", "dead", "removing"}
                        or health not in {"healthy", "unhealthy", "starting", "missing"}
                        or oom not in {"true", "false"}):
                    raise ValueError("invalid Docker state")
                last_state = f"{state}/{health} restarts={int(restarts)} exit={int(exit_code)} oom={oom}"
                last_probe = "docker_not_healthy"
                if state == "running" and health == "healthy":
                    remaining = deadline - time.monotonic()
                    result = probe(["curl", "--fail", "--silent", "--max-time",
                                    str(max(0.001, min(5.0, remaining))),
                                    "--output", "/dev/null", "--write-out", "%{http_code}", url])
                    last_probe = "http_failed"
                    if result.returncode == 0 and result.stdout.strip() == "200" and time.monotonic() < deadline:
                        print(f"HEALTH_READY elapsed={time.monotonic() - started:.3f}s attempts={attempts} {last_state}")
                        return True
        except (OSError, ValueError, subprocess.TimeoutExpired, TimeoutError) as exc:
            # Never emit exception payloads, URL, environment, or application
            # logs. The allowlisted last state is bounded timeout diagnostics.
            last_probe = type(exc).__name__
        remaining = deadline - time.monotonic()
        if remaining > 0:
            time.sleep(min(delay_seconds, remaining))
    print(f"HEALTH_TIMEOUT elapsed={time.monotonic() - started:.3f}s "
          f"limit={timeout_seconds:g}s attempts={attempts} last={last_state} probe={last_probe}", file=sys.stderr)
    return False


if __name__ == "__main__":
    try:
        accepted = check_health(sys.argv[1], float(sys.argv[2]), float(sys.argv[3]))
    except (ValueError, IndexError):
        print("HEALTH_CONFIG_INVALID: bounded numeric timeout/delay required", file=sys.stderr)
        sys.exit(2)
    sys.exit(0 if accepted else 1)
HEALTH_PY
}

set_build_provenance() {
  local sha="$1"
  export SHARIPOVAI_RELEASE_SHA="${sha}"
  export SHARIPOVAI_RELEASE_TAG="${sha:0:12}"
  export SHARIPOVAI_BUILD_DATE="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
}

verify_container_sha() {
  local expected="$1"
  local actual label
  actual="$(docker exec sharipovai printenv SHARIPOVAI_BUILD_SHA 2>/dev/null || true)"
  [[ "${actual}" == "${expected}" ]] || return 1
  # Inspect the *running* container image — do not assume sharipovai:<sha12>.
  label="$(docker inspect --format '{{ index .Config.Labels "org.opencontainers.image.revision" }}' sharipovai 2>/dev/null || true)"
  [[ "${label}" == "${expected}" ]] || return 1
  # The immutable helper survives checkout reset, including a rollback to a
  # revision which predates the helper. Compare structure with the original.
  if [[ -n "${context_helper}" ]]; then
    local project
    project="$(python3 "${context_helper}" --expected-sha "${expected}" --output "${verified_override}")" || return 1
    [[ "${project}" == "${COMPOSE_PROJECT_NAME}" ]] || return 1
    cmp -s "${runtime_override}" "${verified_override}" || return 1
  fi
}

validate_financial_locks() {
  local rendered="$1"
  python3 - "${rendered}" <<'PY'
import json
import sys
from pathlib import Path

payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
service = payload.get("services", {}).get("sharipovai", {})
environment = service.get("environment", {})
if isinstance(environment, list):
    environment = dict(item.split("=", 1) for item in environment if "=" in item)
required = {
    "EXCHANGE_LIVE_TRADING_ENABLED": "0",
    "EXECUTION_KILL_SWITCH": "1",
    "FEATURE_BYBIT_LIVE_EXECUTION": "0",
    "TESTNET_EXECUTION_ENABLED": "0",
    "FEATURE_BYBIT_TESTNET": "0",
    "AUTONOMOUS_TESTNET_ENABLED": "0",
    "AUTONOMOUS_TESTNET_BRIDGE_ENABLED": "0",
    "EXCHANGE_MODE": "sandbox",
}
for key, expected in required.items():
    actual = str(environment.get(key, ""))
    if actual != expected:
        raise SystemExit(f"unsafe compose environment: {key} does not match required lock")
for key in (
    "AUTONOMOUS_TESTNET_BRIDGE_ENABLED",
    "AUTONOMOUS_TESTNET_ENABLED",
    "TESTNET_EXECUTION_ENABLED",
    "FEATURE_BYBIT_TESTNET",
    "FEATURE_BYBIT_LIVE_EXECUTION",
):
    actual = str(environment.get(key, "0")).strip().lower()
    if actual in {"1", "true", "yes", "on"}:
        raise SystemExit(f"unsafe compose environment: {key} is enabled")
PY
}

# F07: source of truth is the running container image ID + OCI revision label.
# Production often uses deploy-prefixed tags (sharipovai:deploy-<sha12>-...), so
# do not assume sharipovai:<sha12> already exists. Retain the verified running
# image under that deterministic rollback reference before building a candidate.
# Rollback must reuse the retained artifact with --no-build (never rebuild).
rollback_image_ref() {
  local sha="$1"
  printf 'sharipovai:%s' "${sha:0:12}"
}

running_container_image_id() {
  local image_id
  image_id="$(docker inspect -f '{{.Image}}' sharipovai 2>/dev/null || true)"
  [[ "${image_id}" =~ ^sha256:[0-9a-f]{64}$ ]] || return 1
  printf '%s\n' "${image_id}"
}

image_oci_revision() {
  local ref="$1"
  docker image inspect -f '{{index .Config.Labels "org.opencontainers.image.revision"}}' "${ref}" 2>/dev/null || true
}

retain_running_image_for_rollback() {
  local expected_sha="$1"
  local image_id revision ref
  image_id="$(running_container_image_id)" \
    || fail "cannot resolve running container image ID; refusing unreproducible rebuild"
  revision="$(image_oci_revision "${image_id}")"
  [[ "${revision}" == "${expected_sha}" ]] \
    || fail "running image OCI revision mismatch: expected ${expected_sha}, got ${revision:-missing}; refusing unreproducible rebuild"
  ref="$(rollback_image_ref "${expected_sha}")"
  docker tag "${image_id}" "${ref}" \
    || fail "failed to retain running image ${image_id} as ${ref}"
  revision="$(image_oci_revision "${ref}")"
  [[ "${revision}" == "${expected_sha}" ]] \
    || fail "retained rollback image ${ref} has wrong OCI revision; refusing unreproducible rebuild"
  log "retained running image ${image_id} as ${ref} (OCI revision verified)"
}

assert_retained_rollback_image() {
  local sha="$1"
  local ref revision
  ref="$(rollback_image_ref "${sha}")"
  docker image inspect "${ref}" >/dev/null 2>&1 \
    || fail "retained rollback image ${ref} is missing; refusing unreproducible rebuild"
  revision="$(image_oci_revision "${ref}")"
  [[ "${revision}" == "${sha}" ]] \
    || fail "retained rollback image ${ref} has wrong OCI revision (${revision:-missing}); refusing unreproducible rebuild"
}

# Compatibility aliases used by contract tests / callers.
pinned_image_ref() { rollback_image_ref "$1"; }
assert_pinned_image_present() { assert_retained_rollback_image "$1"; }

redeploy_retained_release() {
  local sha="$1"
  local context="$2"
  set_build_provenance "${sha}"
  assert_retained_rollback_image "${sha}"
  cd "${compose_dir}"
  local rendered
  rendered="$(mktemp)"
  docker compose config --format json >"${rendered}"
  validate_financial_locks "${rendered}"
  rm -f "${rendered}"
  log "reusing retained image $(rollback_image_ref "${sha}") for ${context} (--no-build)"
  docker compose up -d --no-deps --no-build sharipovai
}

redeploy_pinned_release() { redeploy_retained_release "$1" "$2"; }

rollback() {
  local reason="$1"
  trap - ERR
  if [[ ${rollback_started} -eq 1 ]]; then
    fail "rollback failed after: ${reason}"
  fi
  rollback_started=1
  log "deployment failed: ${reason}; rolling back to ${previous_sha}"
  git -C "${APP_DIR}" reset --hard "${previous_sha}"
  redeploy_pinned_release "${previous_sha}" "failed-deploy rollback"
  health_check || fail 'rollback container did not become healthy'
  verify_container_sha "${previous_sha}" || fail 'rollback container SHA is incorrect'
  fail "new deployment was rolled back safely: ${reason}"
}

if [[ "${FETCH_REMOTE}" == https://github.com/* ]]; then
  log "fetching ${BRANCH} directly over HTTPS"
  git -C "${APP_DIR}" fetch --no-tags "${FETCH_REMOTE}" "${BRANCH}"
  target_sha="$(git -C "${APP_DIR}" rev-parse FETCH_HEAD)"
else
  log "fetching ${FETCH_REMOTE}/${BRANCH}"
  git -C "${APP_DIR}" fetch --prune "${FETCH_REMOTE}" "${BRANCH}"
  target_sha="$(git -C "${APP_DIR}" rev-parse "${FETCH_REMOTE}/${BRANCH}")"
fi
[[ "${target_sha}" =~ ^[0-9a-f]{40}$ ]] || fail 'target commit could not be resolved to a full SHA'
if [[ -n "${EXPECTED_TARGET_SHA}" ]]; then
  [[ "${EXPECTED_TARGET_SHA}" =~ ^[0-9a-f]{40}$ && "${target_sha}" == "${EXPECTED_TARGET_SHA}" ]] \
    || fail 'target SHA differs from the verified release SHA'
fi

if [[ "${target_sha}" == "${previous_sha}" ]]; then
  log "already at ${target_sha}"
  health_check || fail 'current deployment is not healthy'
  verify_container_sha "${target_sha}" || fail 'current container does not embed the deployed SHA; rebuild required'
  exit 0
fi

for target_path in \
  deploy/vps/phase7_preflight.sh \
  deploy/vps/docker-compose.yml \
  deploy/vps/runtime_compose_context.py \
  deploy/vps/export_backup.sh; do
  git -C "${APP_DIR}" cat-file -e "${target_sha}:${target_path}" 2>/dev/null \
    || fail "target artifact is missing: ${target_path}"
done

# Materialize before checkout changes; retain this exact context through rollback.
# A transactional runtime usually belongs to sharipovai-runtime-*, not vps.
context_helper="$(mktemp)"
runtime_override="$(mktemp --suffix=.json)"
verified_override="$(mktemp --suffix=.json)"
git -C "${APP_DIR}" show "${target_sha}:deploy/vps/runtime_compose_context.py" >"${context_helper}"
chmod 0600 "${context_helper}"
python3 -c 'import pathlib, sys; compile(pathlib.Path(sys.argv[1]).read_bytes(), sys.argv[1], "exec")' "${context_helper}"
export COMPOSE_PROJECT_NAME
COMPOSE_PROJECT_NAME="$(python3 "${context_helper}" --expected-sha "${previous_sha}" --output "${runtime_override}")" \
  || fail 'production runtime identity could not be captured'
export COMPOSE_FILE="${compose_dir}/docker-compose.yml:${runtime_override}"
health_check || fail 'current deployment requires Docker healthy and HTTP success'
retain_running_image_for_rollback "${previous_sha}"
assert_retained_rollback_image "${previous_sha}"

log 'materializing immutable target deployment artifacts'
preflight_tmp="$(mktemp)"
target_compose_tmp="$(mktemp --suffix=.yml)"
backup_exporter_tmp="$(mktemp)"
git -C "${APP_DIR}" show "${target_sha}:deploy/vps/phase7_preflight.sh" >"${preflight_tmp}"
git -C "${APP_DIR}" show "${target_sha}:deploy/vps/docker-compose.yml" >"${target_compose_tmp}"
git -C "${APP_DIR}" show "${target_sha}:deploy/vps/export_backup.sh" >"${backup_exporter_tmp}"
chmod 0700 "${preflight_tmp}" "${backup_exporter_tmp}"
bash -n "${preflight_tmp}"
bash -n "${backup_exporter_tmp}"
set_build_provenance "${target_sha}"
rendered_config="$(mktemp)"
docker compose --project-directory "${compose_dir}" --env-file "${compose_dir}/.env.vps" \
  -f "${target_compose_tmp}" -f "${runtime_override}" config --format json >"${rendered_config}"
validate_financial_locks "${rendered_config}"

log 'running immutable target Phase 7 deployment preflight'
APP_DIR="${APP_DIR}" \
COMPOSE_DIR="${compose_dir}" \
PHASE7_COMPOSE_FILE="${target_compose_tmp}" \
bash "${preflight_tmp}"

log 'creating verified backup before code update'
APP_DIR="${APP_DIR}" COMPOSE_DIR="${compose_dir}" bash "${backup_exporter_tmp}"

assert_retained_rollback_image "${previous_sha}"
[[ "$(git -C "${APP_DIR}" rev-parse HEAD)" == "${previous_sha}" \
   && -z "$(git -C "${APP_DIR}" status --porcelain --untracked-files=normal)" ]] \
  || fail 'production checkout changed during preflight'
health_check || fail 'current deployment health changed during preflight'
verify_container_sha "${previous_sha}" || fail 'runtime context changed during preflight'

trap 'rollback "unexpected error at line ${LINENO}"' ERR
log "updating ${previous_sha} -> ${target_sha}"
git -C "${APP_DIR}" checkout -q "${BRANCH}"
git -C "${APP_DIR}" reset --hard "${target_sha}"
chmod 600 "${compose_dir}/.env.vps"
set_build_provenance "${target_sha}"

cd "${compose_dir}"
docker compose config --format json >"${rendered_config}"
validate_financial_locks "${rendered_config}"

log 'building the new image with immutable commit provenance'
docker compose build --pull sharipovai
log 'starting the updated services'
docker compose up -d --no-deps --no-build sharipovai

health_check || rollback 'health endpoint did not recover in time'
container_state="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{end}}' sharipovai 2>/dev/null || true)"
[[ "${container_state}" == "healthy" ]] || rollback "container state is ${container_state:-missing}"
verify_container_sha "${target_sha}" || rollback 'container/image commit provenance mismatch'

trap - ERR
log "deployment completed successfully at ${target_sha}"
docker compose ps
