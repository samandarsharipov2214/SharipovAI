#!/usr/bin/env bash
# Bounded disposable-disk reclaim for self-healing and deploy preflight.
#
# ALLOW: unused sharipovai:deploy-* / sharipovai:<12hex> images that are not the
# live sharipovai/sharipovai-caddy image; at most one rollback image; docker
# builder cache; huge host log tail; leftover .staging-* dirs; backups beyond KEEP.
# FORBID: unbounded system/volume prune, live container rm, paper/sqlite
# DBs, latest.tar.gz (current verified backup), git reset, live/kill-switch flags.
set -Eeuo pipefail

DRY_RUN=0
if [[ "${1:-}" == "--dry-run" ]]; then
  DRY_RUN=1
  shift
fi
if [[ "${SHARIPOVAI_PRUNE_DRY_RUN:-0}" == "1" ]]; then
  DRY_RUN=1
fi
if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  echo "Usage: $0 [--dry-run]" >&2
  exit 64
fi

REPO_DIR="${SHARIPOVAI_REPO_DIR:-${SHARIPOVAI_DEPLOY_ROOT:-/opt/sharipovai-repo}}"
BACKUP_DIR="${SHARIPOVAI_BACKUP_DIR:-$REPO_DIR/deploy/vps/backups}"
HOST_LOG="${SELF_HEALING_HOST_LOG:-/var/log/sharipovai-self-healing-host.log}"
KEEP="${KEEP:-7}"
LOG_KEEP_BYTES="${SELF_HEALING_HOST_LOG_KEEP_BYTES:-10485760}"

if ! [[ "$KEEP" =~ ^[0-9]+$ ]] || (( KEEP < 1 || KEEP > 100 )); then
  echo "PRUNE_FAIL KEEP must be an integer between 1 and 100" >&2
  exit 64
fi
if ! [[ "$LOG_KEEP_BYTES" =~ ^[0-9]+$ ]] || (( LOG_KEEP_BYTES < 1 )); then
  echo "PRUNE_FAIL SELF_HEALING_HOST_LOG_KEEP_BYTES must be a positive integer" >&2
  exit 64
fi

reclaimed=0

emit() {
  printf '%s\n' "$*"
}

add_bytes() {
  local n="${1:-0}"
  [[ "$n" =~ ^[0-9]+$ ]] || n=0
  reclaimed=$((reclaimed + n))
}

file_bytes() {
  local path="$1"
  if [[ -f "$path" ]]; then
    stat -c%s -- "$path" 2>/dev/null || echo 0
  elif [[ -d "$path" ]]; then
    du --apparent-size -sb -- "$path" 2>/dev/null | awk 'NR==1 {print $1}'
  else
    echo 0
  fi
}

is_dry() {
  [[ "$DRY_RUN" == "1" ]]
}

mutate() {
  if is_dry; then
    return 1
  fi
  return 0
}

# --- host log: keep the last N bytes of the same inode when huge ---
prune_host_log() {
  local size keep tmp
  [[ -f "$HOST_LOG" && -w "$HOST_LOG" ]] || {
    emit "PRUNE_SKIP kind=host_log reason=missing_or_unwritable path=$HOST_LOG"
    return 0
  }
  size="$(stat -c%s -- "$HOST_LOG" 2>/dev/null || echo 0)"
  [[ "$size" =~ ^[0-9]+$ ]] || size=0
  if (( size <= LOG_KEEP_BYTES )); then
    emit "PRUNE_KEEP kind=host_log path=$HOST_LOG bytes=$size reason=within_limit"
    return 0
  fi
  keep=$((size - LOG_KEEP_BYTES))
  emit "PRUNE_PLAN kind=host_log path=$HOST_LOG bytes=$keep"
  if mutate; then
    tmp="$(mktemp "${HOST_LOG}.prune.XXXXXX")"
    tail -c "$LOG_KEEP_BYTES" -- "$HOST_LOG" >"$tmp"
    cat -- "$tmp" >"$HOST_LOG"
    rm -f -- "$tmp"
    chmod 0600 "$HOST_LOG" 2>/dev/null || true
    add_bytes "$keep"
  fi
}

# --- leftover backup staging, only if export flock is not held ---
prune_staging() {
  local lock stale size
  if [[ ! -d "$BACKUP_DIR" ]]; then
    emit "PRUNE_SKIP kind=staging reason=backup_dir_missing path=$BACKUP_DIR"
    return 0
  fi
  lock="$BACKUP_DIR/.export.lock"
  exec 8>"$lock" || {
    emit "PRUNE_SKIP kind=staging reason=lock_unwritable path=$lock"
    return 0
  }
  if ! flock -n 8; then
    emit "PRUNE_SKIP kind=staging reason=export_lock_held path=$BACKUP_DIR"
    exec 8>&-
    return 0
  fi
  shopt -s nullglob
  for stale in "$BACKUP_DIR"/.staging-*; do
    [[ -d "$stale" ]] || continue
    [[ "$stale" == "$BACKUP_DIR"/.staging-* ]] || continue
    size="$(file_bytes "$stale")"
    emit "PRUNE_PLAN kind=staging path=$stale bytes=$size"
    if mutate; then
      rm -rf -- "$stale"
      add_bytes "$size"
    fi
  done
  shopt -u nullglob
  flock -u 8 || true
  exec 8>&-
}

current_verified_backup() {
  local latest="$BACKUP_DIR/latest.tar.gz"
  if [[ -L "$latest" || -f "$latest" ]]; then
    readlink -f -- "$latest" 2>/dev/null || true
  fi
}

# --- KEEP newest backups; never delete latest.tar.gz or its target ---
prune_expired_backups() {
  local latest_target archive i size
  if [[ ! -d "$BACKUP_DIR" ]]; then
    emit "PRUNE_SKIP kind=backup reason=backup_dir_missing path=$BACKUP_DIR"
    return 0
  fi
  latest_target="$(current_verified_backup)"
  if [[ -e "$BACKUP_DIR/latest.tar.gz" ]]; then
    emit "PRUNE_KEEP kind=backup path=$BACKUP_DIR/latest.tar.gz reason=current_verified"
  fi
  if [[ -n "$latest_target" ]]; then
    emit "PRUNE_KEEP kind=backup path=$latest_target reason=current_verified_target"
  fi

  local -a archives=()
  while IFS= read -r archive; do
    [[ -n "$archive" ]] || continue
    archives+=("$archive")
  done < <(
    find "$BACKUP_DIR" -maxdepth 1 -type f -name 'sharipovai-*.tar.gz' -printf '%T@ %p\n' \
      | sort -rn | cut -d' ' -f2-
  )

  if ((${#archives[@]} == 0)); then
    return 0
  fi
  for i in "${!archives[@]}"; do
    archive="${archives[$i]}"
    size="$(file_bytes "$archive")"
    if [[ "$archive" == "$BACKUP_DIR/latest.tar.gz" ]]; then
      continue
    fi
    if [[ -n "$latest_target" && "$archive" == "$latest_target" ]]; then
      continue
    fi
    if (( i < KEEP )); then
      emit "PRUNE_KEEP kind=backup path=$archive bytes=$size reason=keep_count"
      continue
    fi
    emit "PRUNE_PLAN kind=backup path=$archive bytes=$size"
    if mutate; then
      rm -f -- "$archive"
      if [[ -f "$archive.sha256" ]]; then
        rm -f -- "$archive.sha256"
      fi
      add_bytes "$size"
    fi
  done
}

is_disposable_tag() {
  local repo="$1" tag="$2"
  [[ "$repo" == "sharipovai" ]] || return 1
  [[ "$tag" != "<none>" && -n "$tag" ]] || return 1
  if [[ "$tag" == deploy-* ]]; then
    return 0
  fi
  if [[ "$tag" =~ ^[0-9a-f]{12}$ ]]; then
    return 0
  fi
  return 1
}

# --- unused deploy images; fail closed if live image cannot be proven ---
prune_docker_images() {
  local live_app live_caddy name cid image created running ps_out img_out
  local id repo tag size keep_rollback keep_created
  if ! command -v docker >/dev/null 2>&1; then
    emit "PRUNE_IMAGES_FAIL_CLOSED reason=docker_missing"
    return 0
  fi

  if ! live_app="$(docker inspect -f '{{.Image}}' sharipovai 2>/dev/null)"; then
    emit "PRUNE_IMAGES_FAIL_CLOSED reason=live_image_unknown container=sharipovai"
    return 0
  fi
  if ! live_caddy="$(docker inspect -f '{{.Image}}' sharipovai-caddy 2>/dev/null)"; then
    emit "PRUNE_IMAGES_FAIL_CLOSED reason=live_image_unknown container=sharipovai-caddy"
    return 0
  fi
  if [[ ! "$live_app" =~ ^sha256:[0-9a-f]{64}$ ]]; then
    emit "PRUNE_IMAGES_FAIL_CLOSED reason=live_image_unknown container=sharipovai value=$live_app"
    return 0
  fi
  if [[ -z "$live_caddy" ]]; then
    emit "PRUNE_IMAGES_FAIL_CLOSED reason=live_image_unknown container=sharipovai-caddy"
    return 0
  fi

  emit "PRUNE_KEEP kind=image id=$live_app reason=live container=sharipovai"
  emit "PRUNE_KEEP kind=image id=$live_caddy reason=live container=sharipovai-caddy"

  if ! ps_out="$(docker ps -a --format '{{.Names}}|{{.ID}}')"; then
    emit "PRUNE_IMAGES_FAIL_CLOSED reason=container_list_failed"
    return 0
  fi
  if ! img_out="$(docker images --no-trunc --format '{{.ID}}|{{.Repository}}|{{.Tag}}')"; then
    emit "PRUNE_IMAGES_FAIL_CLOSED reason=image_list_failed"
    return 0
  fi

  keep_rollback=""
  keep_created=""
  while IFS='|' read -r name cid; do
    [[ -n "$name" && -n "$cid" ]] || continue
    [[ "$name" == sharipovai-rollback-* ]] || continue
    if ! IFS='|' read -r image created running < <(
      docker inspect -f '{{.Image}}|{{.Created}}|{{.State.Running}}' "$cid" 2>/dev/null
    ); then
      emit "PRUNE_IMAGES_FAIL_CLOSED reason=rollback_inspect_failed container=$name"
      return 0
    fi
    if [[ -z "$keep_created" || "$created" > "$keep_created" ]]; then
      keep_rollback="$image"
      keep_created="$created"
    fi
  done <<<"$ps_out"

  declare -A tag_of_id=()
  declare -A created_of_id=()
  declare -A size_of_id=()
  declare -A seen_id=()
  local -a ordered_ids=()

  while IFS='|' read -r id repo tag; do
    [[ -n "$id" ]] || continue
    is_disposable_tag "$repo" "$tag" || continue
    if [[ -z "${seen_id[$id]+x}" ]]; then
      seen_id["$id"]=1
      ordered_ids+=("$id")
      if ! IFS='|' read -r size created < <(
        docker image inspect -f '{{.Size}}|{{.Created}}' "$id" 2>/dev/null
      ); then
        emit "PRUNE_IMAGES_FAIL_CLOSED reason=image_inspect_failed id=$id"
        return 0
      fi
      size_of_id["$id"]="$size"
      created_of_id["$id"]="$created"
    fi
    if [[ -n "${tag_of_id[$id]:-}" ]]; then
      tag_of_id["$id"]="${tag_of_id[$id]},sharipovai:$tag"
    else
      tag_of_id["$id"]="sharipovai:$tag"
    fi
  done <<<"$img_out"

  if [[ -z "$keep_rollback" ]]; then
    local newest_id="" newest_created=""
    if ((${#ordered_ids[@]} > 0)); then
      for id in "${ordered_ids[@]}"; do
        [[ "$id" == "$live_app" || "$id" == "$live_caddy" ]] && continue
        created="${created_of_id[$id]}"
        if [[ -z "$newest_created" || "$created" > "$newest_created" ]]; then
          newest_id="$id"
          newest_created="$created"
        fi
      done
    fi
    keep_rollback="$newest_id"
  fi

  if [[ -n "$keep_rollback" ]]; then
    emit "PRUNE_KEEP kind=image id=$keep_rollback ref=${tag_of_id[$keep_rollback]:-} reason=rollback"
  fi

  if ((${#ordered_ids[@]} == 0)); then
    return 0
  fi
  for id in "${ordered_ids[@]}"; do
    if [[ "$id" == "$live_app" || "$id" == "$live_caddy" || "$id" == "$keep_rollback" ]]; then
      emit "PRUNE_KEEP kind=image id=$id ref=${tag_of_id[$id]:-} reason=protected_live_or_rollback"
      continue
    fi
    size="${size_of_id[$id]:-0}"
    emit "PRUNE_PLAN kind=image id=$id ref=${tag_of_id[$id]:-} bytes=$size"
    if mutate; then
      if docker image rm "$id" >/dev/null 2>&1; then
        add_bytes "$size"
      else
        emit "PRUNE_SKIP kind=image id=$id reason=in_use_or_remove_failed"
      fi
    fi
  done
}

prune_builder_cache() {
  if ! command -v docker >/dev/null 2>&1; then
    emit "PRUNE_SKIP kind=builder_cache reason=docker_missing"
    return 0
  fi
  emit "PRUNE_PLAN kind=builder_cache"
  if mutate; then
    local output
    if output="$(docker builder prune -f 2>&1)"; then
      printf '%s\n' "$output"
      local human
      human="$(printf '%s\n' "$output" | awk 'tolower($0) ~ /total/ {print $NF; exit}')"
      # Best-effort: if docker reported an integer byte count, add it.
      if [[ "$human" =~ ^[0-9]+[Bb]$ ]]; then
        add_bytes "${human%[Bb]}"
      fi
    else
      emit "PRUNE_SKIP kind=builder_cache reason=builder_prune_failed"
    fi
  fi
}

prune_host_log
prune_staging
prune_expired_backups
prune_docker_images
prune_builder_cache

emit "PRUNE_DISPOSABLE_DISK_RECLAIMED_BYTES=$reclaimed"
if is_dry; then
  emit "PRUNE_DRY_RUN=1"
fi
