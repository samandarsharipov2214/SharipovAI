#!/usr/bin/env bash
set -Eeuo pipefail

MODE="${1:-inspect}"
MIN_FREE_GIB="${SHARIPOVAI_DEPLOY_MIN_FREE_DISK_GB:-20}"
SERVICE="${SHARIPOVAI_SERVICE_NAME:-sharipovai}"
ROOT="${SHARIPOVAI_DEPLOY_ROOT:-/opt/sharipovai-repo}"
LEGACY_REF="${SHARIPOVAI_LEGACY_IMAGE_REF:-vps-sharipovai:latest}"
LEGACY_MIN_AGE_DAYS="${SHARIPOVAI_LEGACY_IMAGE_MIN_AGE_DAYS:-14}"
JOURNAL_MAX_SIZE="${SHARIPOVAI_JOURNAL_MAX_SIZE:-256M}"

[[ "$MODE" == "inspect" || "$MODE" == "apply" ]] || {
  echo "Usage: $0 {inspect|apply}" >&2
  exit 64
}
for value in "$MIN_FREE_GIB" "$LEGACY_MIN_AGE_DAYS"; do
  [[ "$value" =~ ^[1-9][0-9]*$ ]] || {
    echo "numeric limits must be positive integers" >&2
    exit 64
  }
done
[[ "$ROOT" == /* ]] || { echo "deploy root must be absolute" >&2; exit 64; }
command -v docker >/dev/null 2>&1 || { echo "docker is required" >&2; exit 69; }

available_kb() {
  df -Pk "$ROOT" | awk 'NR==2 {print $4}'
}

minimum_kb="$((MIN_FREE_GIB * 1024 * 1024))"

image_id_for_ref() {
  docker image inspect -f '{{.Id}}' "$1" 2>/dev/null || true
}

image_tags_for_id() {
  docker image inspect -f '{{range .RepoTags}}{{println .}}{{end}}' "$1" 2>/dev/null || true
}

container_uses_image() {
  local image_id="$1"
  local found=1
  while IFS= read -r cid; do
    [[ -n "$cid" ]] || continue
    if [[ "$(docker inspect -f '{{.Image}}' "$cid" 2>/dev/null || true)" == "$image_id" ]]; then
      found=0
      break
    fi
  done < <(docker ps -aq)
  return "$found"
}

is_running_image() {
  local image_id="$1"
  local found=1
  while IFS= read -r cid; do
    [[ -n "$cid" ]] || continue
    if [[ "$(docker inspect -f '{{.Image}}' "$cid" 2>/dev/null || true)" == "$image_id" ]]; then
      found=0
      break
    fi
  done < <(docker ps -q)
  return "$found"
}

current_image_id="$(docker container inspect -f '{{.Image}}' "$SERVICE" 2>/dev/null || true)"
[[ "$current_image_id" =~ ^sha256:[0-9a-f]{64}$ ]] || {
  echo "cannot resolve current production image for $SERVICE" >&2
  exit 70
}

rollback_image_id=""
rollback_image_ref=""
while IFS= read -r ref; do
  [[ -n "$ref" ]] || continue
  id="$(image_id_for_ref "$ref")"
  [[ -n "$id" ]] || continue
  if [[ "$id" != "$current_image_id" ]]; then
    rollback_image_id="$id"
    rollback_image_ref="$ref"
    break
  fi
done < <(docker image ls --filter 'reference=sharipovai:deploy-*' --format '{{.Repository}}:{{.Tag}}')

protected_image() {
  local image_id="$1"
  [[ "$image_id" == "$current_image_id" ]] && return 0
  [[ -n "$rollback_image_id" && "$image_id" == "$rollback_image_id" ]] && return 0
  is_running_image "$image_id" && return 0
  while IFS= read -r tag; do
    [[ -n "$tag" ]] || continue
    case "$tag" in
      *rollback*|*recovery*) return 0 ;;
    esac
  done < <(image_tags_for_id "$image_id")
  return 1
}

print_summary() {
  echo "current_production_image=$current_image_id"
  echo "protected_previous_deploy_ref=${rollback_image_ref:-none}"
  echo "protected_previous_deploy_image=${rollback_image_id:-none}"
  echo "free_kb=$(available_kb)"
  echo "minimum_kb=$minimum_kb"
  df -h "$ROOT" || true
  docker system df || true
}

candidate_containers=()
candidate_images=()

while IFS= read -r cid; do
  [[ -n "$cid" ]] || continue
  image_id="$(docker inspect -f '{{.Image}}' "$cid" 2>/dev/null || true)"
  [[ "$image_id" =~ ^sha256:[0-9a-f]{64}$ ]] || continue
  if protected_image "$image_id"; then
    continue
  fi
  candidate_containers+=("$cid")
  candidate_images+=("$image_id")
done < <(
  docker ps -a \
    --filter 'label=ai.sharipov.service=data-permissions' \
    --filter 'status=exited' \
    --format '{{.ID}}'
)

legacy_image_id="$(image_id_for_ref "$LEGACY_REF")"
legacy_safe=0
if [[ "$legacy_image_id" =~ ^sha256:[0-9a-f]{64}$ ]] && ! protected_image "$legacy_image_id"; then
  if ! container_uses_image "$legacy_image_id"; then
    created="$(docker image inspect -f '{{.Created}}' "$legacy_image_id" 2>/dev/null || true)"
    created_epoch="$(date -d "$created" +%s 2>/dev/null || echo 0)"
    now_epoch="$(date +%s)"
    min_age_seconds="$((LEGACY_MIN_AGE_DAYS * 86400))"
    if (( created_epoch > 0 && now_epoch - created_epoch >= min_age_seconds )); then
      legacy_safe=1
    fi
  fi
fi

echo "=== SharipovAI bounded storage reclaim ==="
print_summary

echo
echo "stale_data_permission_containers=${#candidate_containers[@]}"
for i in "${!candidate_containers[@]}"; do
  echo "candidate_container=${candidate_containers[$i]} image=${candidate_images[$i]} tags=$(image_tags_for_id "${candidate_images[$i]}" | tr '\n' ',')"
done
if [[ "$legacy_safe" == "1" ]]; then
  echo "candidate_legacy_image=$LEGACY_REF id=$legacy_image_id"
else
  echo "candidate_legacy_image=none"
fi

if [[ "$MODE" == "inspect" ]]; then
  echo "DRY_RUN_ONLY: pass apply to perform only the listed bounded cleanup."
  exit 0
fi

for i in "${!candidate_containers[@]}"; do
  cid="${candidate_containers[$i]}"
  image_id="${candidate_images[$i]}"
  echo "Removing exited data-permissions container $cid"
  docker rm "$cid"

  if protected_image "$image_id"; then
    echo "Keeping image $image_id because it became protected."
    continue
  fi
  if container_uses_image "$image_id"; then
    echo "Keeping image $image_id because another container still references it."
    continue
  fi
  echo "Removing now-unreferenced stale data-permissions image $image_id"
  docker image rm "$image_id" || true
done

if [[ "$legacy_safe" == "1" ]]; then
  if ! protected_image "$legacy_image_id" && ! container_uses_image "$legacy_image_id"; then
    echo "Removing unused legacy image $LEGACY_REF"
    docker image rm "$LEGACY_REF" || true
  fi
fi

# Host package cache and old systemd journal entries are disposable operating
# system maintenance data. They are only touched if image cleanup alone still
# leaves deploy headroom below the fail-closed threshold.
if (( $(available_kb) < minimum_kb )); then
  if command -v apt-get >/dev/null 2>&1; then
    echo "Cleaning APT package cache."
    apt-get clean || true
  fi
fi
if (( $(available_kb) < minimum_kb )); then
  if command -v journalctl >/dev/null 2>&1; then
    echo "Bounding systemd journal to $JOURNAL_MAX_SIZE."
    journalctl --vacuum-size="$JOURNAL_MAX_SIZE" || true
  fi
fi

final_kb="$(available_kb)"
echo
echo "=== after bounded cleanup ==="
print_summary

if (( final_kb < minimum_kb )); then
  echo "STORAGE_RECLAIM_INSUFFICIENT available_kb=$final_kb minimum_kb=$minimum_kb" >&2
  exit 70
fi

echo "STORAGE_RECLAIM_OK available_kb=$final_kb minimum_kb=$minimum_kb"
