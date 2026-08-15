#!/usr/bin/env bash
set -Eeuo pipefail

MODE="${1:-}"
ROOT="${SHARIPOVAI_DEPLOY_ROOT:-/opt/sharipovai-repo}"
MIN_FREE_DISK_GB="${SHARIPOVAI_DEPLOY_MIN_FREE_DISK_GB:-20}"
PRUNE_TIMEOUT_SECONDS="${SHARIPOVAI_BUILD_CACHE_PRUNE_TIMEOUT_SECONDS:-180}"

for value in "$MIN_FREE_DISK_GB" "$PRUNE_TIMEOUT_SECONDS"; do
  [[ "$value" =~ ^[1-9][0-9]*$ ]] || {
    echo "Storage guard values must be positive integers." >&2
    exit 64
  }
done
[[ "$ROOT" == /* ]] || {
  echo "SHARIPOVAI_DEPLOY_ROOT must be an absolute path." >&2
  exit 64
}

available_kb() {
  df -Pk "$ROOT" | awk 'NR==2 {print $4}'
}

print_disk() {
  df -h "$ROOT" >&2 || true
}

prune_build_cache() {
  if ! command -v docker >/dev/null 2>&1; then
    echo "STORAGE_GUARD_PRUNE_UNAVAILABLE docker command is missing." >&2
    return 1
  fi
  echo "STORAGE_GUARD_PRUNE_BUILD_CACHE starting disposable BuildKit cache cleanup."
  timeout --signal=TERM --kill-after=30s "${PRUNE_TIMEOUT_SECONDS}s" docker builder prune -af
}

case "$MODE" in
  preflight)
    minimum_kb="$((MIN_FREE_DISK_GB * 1024 * 1024))"
    before_kb="$(available_kb)"
    if [[ ! "$before_kb" =~ ^[0-9]+$ ]]; then
      echo "STORAGE_GUARD_DISK_UNKNOWN: cannot determine free disk space." >&2
      print_disk
      exit 70
    fi
    if (( before_kb >= minimum_kb )); then
      echo "STORAGE_GUARD_PREFLIGHT_OK available_kb=$before_kb minimum_kb=$minimum_kb"
      exit 0
    fi

    echo "STORAGE_GUARD_PRESSURE available_kb=$before_kb minimum_kb=$minimum_kb; reclaiming only unused Docker build cache." >&2
    prune_build_cache || true
    after_kb="$(available_kb)"
    if [[ ! "$after_kb" =~ ^[0-9]+$ ]] || (( after_kb < minimum_kb )); then
      echo "STORAGE_GUARD_PREFLIGHT_FAILED: require at least ${MIN_FREE_DISK_GB} GiB free after safe build-cache cleanup." >&2
      print_disk
      exit 70
    fi
    echo "STORAGE_GUARD_RECOVERED available_kb=$after_kb minimum_kb=$minimum_kb"
    ;;

  cleanup)
    before_kb="$(available_kb 2>/dev/null || true)"
    # A 60 GiB VPS cannot safely retain multi-gigabyte build layers after each
    # deployment. This removes only unused BuildKit cache; images, containers,
    # volumes, databases, backups and evidence are outside this command's scope.
    if prune_build_cache; then
      after_kb="$(available_kb 2>/dev/null || true)"
      echo "STORAGE_GUARD_POST_DEPLOY_CLEANUP_OK before_kb=${before_kb:-unknown} after_kb=${after_kb:-unknown}"
    else
      # Post-deploy cleanup is best-effort and must never overwrite the original
      # transactional deploy result. The next preflight will still fail closed.
      echo "STORAGE_GUARD_POST_DEPLOY_CLEANUP_WARNING build cache cleanup did not complete." >&2
    fi
    ;;

  *)
    echo "Usage: $0 {preflight|cleanup}" >&2
    exit 64
    ;;
esac
