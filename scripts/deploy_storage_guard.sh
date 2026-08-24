#!/usr/bin/env bash
set -Eeuo pipefail

MODE="${1:-}"
ROOT="${SHARIPOVAI_DEPLOY_ROOT:-/opt/sharipovai-repo}"
MIN_FREE_DISK_GB="${SHARIPOVAI_DEPLOY_MIN_FREE_DISK_GB:-20}"

[[ "$MIN_FREE_DISK_GB" =~ ^[1-9][0-9]*$ ]] || {
  echo "Storage guard values must be positive integers." >&2
  exit 64
}
[[ "$ROOT" == /* ]] || {
  echo "SHARIPOVAI_DEPLOY_ROOT must be an absolute path." >&2
  exit 64
}

available_kb() {
  df -Pk "$ROOT" | awk 'NR==2 {print $4}'
}

print_fresh_disk_evidence() {
  echo "STORAGE_GUARD_EVIDENCE_UTC $(date -u +%Y-%m-%dT%H:%M:%SZ)"
  if ! df -h "$ROOT" >&2; then
    echo "STORAGE_GUARD_HOST_DF_UNAVAILABLE required df -h evidence failed." >&2
    return 70
  fi
  if ! command -v docker >/dev/null 2>&1; then
    echo "STORAGE_GUARD_DOCKER_DF_UNAVAILABLE docker command is missing." >&2
    return 70
  fi
  if ! docker system df >&2; then
    echo "STORAGE_GUARD_DOCKER_DF_UNAVAILABLE docker system df failed." >&2
    return 70
  fi
}

case "$MODE" in
  preflight)
    minimum_kb="$((MIN_FREE_DISK_GB * 1024 * 1024))"
    if ! current_kb="$(available_kb)"; then
      echo "STORAGE_GUARD_DISK_UNKNOWN: cannot determine free disk space." >&2
      exit 70
    fi
    if ! print_fresh_disk_evidence; then
      exit 70
    fi
    if [[ ! "$current_kb" =~ ^[0-9]+$ ]]; then
      echo "STORAGE_GUARD_DISK_UNKNOWN: cannot determine free disk space." >&2
      exit 70
    fi
    if (( current_kb < minimum_kb )); then
      echo "STORAGE_GUARD_PRESSURE available_kb=$current_kb minimum_kb=$minimum_kb; automatic cleanup is disabled. Prove and approve a specific unused object before any targeted cleanup." >&2
      exit 70
    fi
    echo "STORAGE_GUARD_PREFLIGHT_OK available_kb=$current_kb minimum_kb=$minimum_kb"
    ;;

  cleanup)
    # Cleanup is intentionally read-only. Deploy automation must never delete
    # Docker objects implicitly; any targeted cleanup requires separate proof
    # that the exact object is unused and explicit operator approval.
    if ! current_kb="$(available_kb)"; then
      echo "STORAGE_GUARD_DISK_UNKNOWN: cannot determine free disk space." >&2
      exit 70
    fi
    if ! print_fresh_disk_evidence; then
      exit 70
    fi
    echo "STORAGE_GUARD_CLEANUP_SKIPPED automatic cleanup disabled available_kb=$current_kb"
    ;;

  *)
    echo "Usage: $0 {preflight|cleanup}" >&2
    exit 64
    ;;
esac
