#!/usr/bin/env bash
set -Eeuo pipefail

MODE="${1:-}"
ROOT="${SHARIPOVAI_DEPLOY_ROOT:-/opt/sharipovai-repo}"
MIN_FREE_DISK_GB="${SHARIPOVAI_DEPLOY_MIN_FREE_DISK_GB:-20}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PRUNE_HELPER="${SHARIPOVAI_PRUNE_HELPER:-$SCRIPT_DIR/../deploy/vps/prune_disposable_disk.sh}"

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

run_bounded_disposable_prune() {
  if [[ ! -r "$PRUNE_HELPER" ]]; then
    echo "STORAGE_GUARD_PRUNE_HELPER_MISSING $PRUNE_HELPER" >&2
    return 65
  fi
  # Helper is fail-closed: it never deletes live images, volumes, paper DBs,
  # or latest.tar.gz. It may reclaim unused sharipovai:deploy-* images,
  # builder cache, huge host logs, leftover staging, and backups beyond KEEP.
  SHARIPOVAI_DEPLOY_ROOT="$ROOT" \
  SHARIPOVAI_REPO_DIR="$ROOT" \
  bash "$PRUNE_HELPER"
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
      echo "STORAGE_GUARD_PRESSURE available_kb=$current_kb minimum_kb=$minimum_kb; attempting bounded disposable prune." >&2
      run_bounded_disposable_prune || true
      if ! print_fresh_disk_evidence; then
        exit 70
      fi
      if ! current_kb="$(available_kb)"; then
        echo "STORAGE_GUARD_DISK_UNKNOWN: cannot determine free disk space." >&2
        exit 70
      fi
      if [[ ! "$current_kb" =~ ^[0-9]+$ ]] || (( current_kb < minimum_kb )); then
        echo "STORAGE_GUARD_PRESSURE available_kb=$current_kb minimum_kb=$minimum_kb; bounded disposable prune did not restore 20GiB headroom." >&2
        exit 70
      fi
    fi
    echo "STORAGE_GUARD_PREFLIGHT_OK available_kb=$current_kb minimum_kb=$minimum_kb"
    ;;

  cleanup)
    if ! current_kb="$(available_kb)"; then
      echo "STORAGE_GUARD_DISK_UNKNOWN: cannot determine free disk space." >&2
      exit 70
    fi
    if ! print_fresh_disk_evidence; then
      exit 70
    fi
    if ! prune_output="$(run_bounded_disposable_prune)"; then
      echo "STORAGE_GUARD_CLEANUP_FAILED bounded disposable prune failed closed available_kb=$current_kb" >&2
      printf '%s\n' "$prune_output"
      exit 70
    fi
    printf '%s\n' "$prune_output"
    echo "STORAGE_GUARD_CLEANUP_OK available_kb=$current_kb"
    ;;

  *)
    echo "Usage: $0 {preflight|cleanup}" >&2
    exit 64
    ;;
esac
