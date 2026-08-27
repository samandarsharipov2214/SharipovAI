#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

APP_DIR=${APP_DIR:-/opt/sharipovai-repo}
COMPOSE_DIR=${COMPOSE_DIR:-$APP_DIR/deploy/vps}
BACKUP_DIR=${BACKUP_DIR:-$COMPOSE_DIR/backups}
CONTAINER=${CONTAINER:-sharipovai}
KEEP=${KEEP:-7}
MIN_FREE_DISK_GB=${SHARIPOVAI_BACKUP_MIN_FREE_DISK_GB:-20}
RESERVE_MIB=${SHARIPOVAI_BACKUP_RESERVE_MIB:-512}
HELPER_TIMEOUT_SECONDS=${SHARIPOVAI_BACKUP_HELPER_TIMEOUT_SECONDS:-300}
SIZE_PROBE_TIMEOUT_SECONDS=${SHARIPOVAI_BACKUP_SIZE_PROBE_TIMEOUT_SECONDS:-60}

fail() { printf '[backup] ERROR: %s\n' "$*" >&2; exit 1; }
log() { printf '[backup] %s\n' "$*"; }

if ! [[ "$KEEP" =~ ^[0-9]+$ ]] || (( KEEP < 1 || KEEP > 100 )); then
  fail 'KEEP must be an integer between 1 and 100'
fi
if ! [[ "$MIN_FREE_DISK_GB" =~ ^[0-9]+$ ]] || (( MIN_FREE_DISK_GB < 1 || MIN_FREE_DISK_GB > 1024 )); then
  fail 'SHARIPOVAI_BACKUP_MIN_FREE_DISK_GB must be an integer between 1 and 1024'
fi
if ! [[ "$RESERVE_MIB" =~ ^[0-9]+$ ]] || (( RESERVE_MIB > 1048576 )); then
  fail 'SHARIPOVAI_BACKUP_RESERVE_MIB must be an integer between 0 and 1048576'
fi
if ! [[ "$HELPER_TIMEOUT_SECONDS" =~ ^[0-9]+$ ]] || (( HELPER_TIMEOUT_SECONDS < 30 || HELPER_TIMEOUT_SECONDS > 3600 )); then
  fail 'SHARIPOVAI_BACKUP_HELPER_TIMEOUT_SECONDS must be an integer between 30 and 3600'
fi
if ! [[ "$SIZE_PROBE_TIMEOUT_SECONDS" =~ ^[0-9]+$ ]] || (( SIZE_PROBE_TIMEOUT_SECONDS < 5 || SIZE_PROBE_TIMEOUT_SECONDS > 600 )); then
  fail 'SHARIPOVAI_BACKUP_SIZE_PROBE_TIMEOUT_SECONDS must be an integer between 5 and 600'
fi

MIN_FREE_BYTES=$((MIN_FREE_DISK_GB * 1024 * 1024 * 1024))
RESERVE_BYTES=$((RESERVE_MIB * 1024 * 1024))

run_low_priority() {
  if command -v ionice >/dev/null 2>&1 && command -v nice >/dev/null 2>&1; then
    ionice -c2 -n7 nice -n 10 "$@"
  elif command -v nice >/dev/null 2>&1; then
    nice -n 10 "$@"
  else
    "$@"
  fi
}

mkdir -p "$BACKUP_DIR"
chmod 700 "$BACKUP_DIR"
BACKUP_DIR=$(cd "$BACKUP_DIR" && pwd -P)
exec 9>"$BACKUP_DIR/.export.lock"
if ! flock -n 9; then
  fail 'backup export is already running'
fi

cleanup_stale_staging() {
  local stale removed=0
  while IFS= read -r -d '' stale; do
    [[ "$stale" == "$BACKUP_DIR"/.staging-* ]] || fail "refusing unsafe staging cleanup path: $stale"
    rm -rf -- "$stale"
    removed=$((removed + 1))
  done < <(find "$BACKUP_DIR" -mindepth 1 -maxdepth 1 -type d -name '.staging-*' -print0)
  if (( removed > 0 )); then
    log "removed $removed stale staging director$( (( removed == 1 )) && printf 'y' || printf 'ies' )"
  fi
}

available_backup_bytes() {
  local value
  value=$(df -P -B1 "$BACKUP_DIR" 2>/dev/null | awk 'NR == 2 {print $4}') || fail 'could not inspect backup filesystem free space'
  [[ "$value" =~ ^[0-9]+$ ]] || fail 'backup filesystem free space is unavailable'
  printf '%s\n' "$value"
}

require_free_space() {
  local extra_bytes=$1
  local phase=$2
  local available required
  [[ "$extra_bytes" =~ ^[0-9]+$ ]] || fail "invalid disk reservation for $phase"
  available=$(available_backup_bytes)
  required=$((MIN_FREE_BYTES + RESERVE_BYTES + extra_bytes))
  if (( available < required )); then
    fail "disk preflight failed at $phase: available=${available}B required=${required}B (minimum free=${MIN_FREE_DISK_GB}GiB reserve=${RESERVE_MIB}MiB extra=${extra_bytes}B)"
  fi
  log "disk preflight passed at $phase: available=${available}B required=${required}B"
}

cleanup_stale_staging
require_free_space 0 'initial preflight'
command -v timeout >/dev/null 2>&1 || fail 'timeout command is required for bounded backup operations'

stamp=$(date -u +%Y%m%dT%H%M%SZ)
run_id="${stamp}-$$"
helper_name="sharipovai-backup-helper-${run_id}"
work=''
archive_tmp=''
archive_checksum_tmp=''

cleanup_backup_helper() {
  local helper_id role helper_run
  [[ -n "${helper_name:-}" && -n "${run_id:-}" ]] || return 0
  helper_id=$(docker inspect --format '{{.Id}}' "$helper_name" 2>/dev/null || true)
  [[ -n "$helper_id" ]] || return 0
  role=$(docker inspect --format '{{index .Config.Labels "com.sharipovai.role"}}' "$helper_id" 2>/dev/null || true)
  helper_run=$(docker inspect --format '{{index .Config.Labels "com.sharipovai.run"}}' "$helper_id" 2>/dev/null || true)
  if [[ "$role" == 'backup-helper' && "$helper_run" == "$run_id" ]]; then
    docker rm -f "$helper_id" >/dev/null 2>&1 || true
  else
    log "refusing to remove helper candidate with unexpected labels: $helper_id"
  fi
}

cleanup() {
  local candidate
  cleanup_backup_helper
  if [[ -n "${work:-}" ]]; then
    if [[ "$work" == "$BACKUP_DIR"/.staging-* ]]; then
      rm -rf -- "$work"
    else
      log "refusing unsafe work cleanup path: $work"
    fi
  fi
  for candidate in "${archive_tmp:-}" "${archive_checksum_tmp:-}"; do
    [[ -n "$candidate" ]] || continue
    if [[ "$candidate" == "$BACKUP_DIR"/.sharipovai-*.partial-* ]]; then
      rm -f -- "$candidate"
    else
      log "refusing unsafe partial archive cleanup path: $candidate"
    fi
  done
  if [[ -n "${archive:-}" && ! -e "$archive" && -e "$archive.sha256" ]]; then
    rm -f -- "$archive.sha256"
  fi
}
trap cleanup EXIT

work=$(mktemp -d "$BACKUP_DIR/.staging-$stamp-XXXXXX")
archive="$BACKUP_DIR/sharipovai-$stamp.tar.gz"
if [[ -e "$archive" || -e "$archive.sha256" ]]; then
  fail "backup archive already exists for timestamp $stamp"
fi
mkdir -p "$work/data"

cd "$COMPOSE_DIR"
source_mode='stopped-volume-readonly'
fixed_container_ids=''
if ! fixed_container_ids=$(docker container ls -a --no-trunc \
  --filter "name=^/${CONTAINER}$" --format '{{.ID}}' 2>/dev/null); then
  fail 'could not inspect fixed-name application container inventory'
fi
readarray -t fixed_containers <<<"$fixed_container_ids"
if [[ -n "${fixed_containers[0]:-}" ]]; then
  (( ${#fixed_containers[@]} == 1 )) || fail 'multiple fixed-name application containers were detected'
  container_id=${fixed_containers[0]}
else
  # Initial and compatibility deployments may still belong to the default
  # Compose project without a fixed container name. Transactional deploys use
  # the canonical fixed name and are found above regardless of project name.
  if ! container_id=$(docker compose ps -a -q "$CONTAINER" 2>/dev/null); then
    fail 'could not inspect default Compose application runtime'
  fi
fi
running='false'
if [[ -n "$container_id" ]]; then
  if ! canonical_container_id=$(docker inspect --format '{{.Id}}' "$container_id" 2>/dev/null); then
    fail 'could not inspect application container identity'
  fi
  [[ -n "$canonical_container_id" ]] || fail 'application container identity is empty'
  container_id=$canonical_container_id
  runtime_service=$(docker inspect --format '{{index .Config.Labels "ai.sharipov.service"}}' "$container_id" 2>/dev/null) \
    || fail 'could not inspect application service identity'
  runtime_mode=$(docker inspect --format '{{index .Config.Labels "ai.sharipov.runtime-mode"}}' "$container_id" 2>/dev/null) \
    || fail 'could not inspect application runtime mode'
  compose_service=$(docker inspect --format '{{index .Config.Labels "com.docker.compose.service"}}' "$container_id" 2>/dev/null) \
    || fail 'could not inspect application Compose service identity'
  [[ "$runtime_service" == 'dashboard' && "$runtime_mode" == 'production-safe' && "$compose_service" == "$CONTAINER" ]] \
    || fail 'application container has an unexpected production identity'
  running=$(docker inspect --format '{{.State.Running}}' "$container_id" 2>/dev/null) \
    || fail 'could not inspect application container state'
  [[ "$running" == 'true' || "$running" == 'false' ]] || fail 'application container state is invalid'
fi

if [[ "$running" == 'true' ]]; then
  source_mode='running-volume-readonly'
  log 'creating transactionally consistent backup through isolated read-only helper'
else
  log 'application container is stopped; creating read-only backup directly from persistent volume'
fi

volume_name=''
image_name=''
if [[ -n "$container_id" ]]; then
  detected_volume=$(docker inspect --format '{{range .Mounts}}{{if eq .Destination "/var/lib/sharipovai"}}{{.Name}}{{end}}{{end}}' "$container_id" 2>/dev/null) \
    || fail 'could not inspect live persistent data volume'
  detected_image=$(docker inspect --format '{{.Config.Image}}' "$container_id" 2>/dev/null) \
    || fail 'could not inspect live application image'
  [[ -n "$detected_volume" ]] || fail 'live persistent data volume is missing'
  [[ -n "$detected_image" ]] || fail 'live application image is missing'
  volume_name=$detected_volume
  image_name=$detected_image
else
  rendered=$(mktemp "$work/compose-config.XXXXXX")
  docker compose config --format json >"$rendered"
  readarray -t backup_runtime < <(python3 - "$rendered" "$CONTAINER" <<'PY'
import json
import sys
from pathlib import Path

payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
service_name = sys.argv[2]
service = payload.get("services", {}).get(service_name, {})
volume = payload.get("volumes", {}).get("sharipovai_data", {})
print(str(volume.get("name", "")))
print(str(service.get("image", "")))
PY
  )
  rm -f "$rendered"
  volume_name=${backup_runtime[0]:-}
  image_name=${backup_runtime[1]:-}
fi

[[ "$volume_name" =~ ^[A-Za-z0-9_.-]+$ ]] || fail 'persistent data volume could not be resolved safely'
docker volume inspect "$volume_name" >/dev/null 2>&1 || fail "persistent data volume is missing: $volume_name"
if ! docker image inspect "$image_name" >/dev/null 2>&1; then
  image_name=$(docker image ls \
    --filter 'label=org.opencontainers.image.title=SharipovAI OS' \
    --format '{{.Repository}}:{{.Tag}}' | head -n 1)
fi
[[ -n "$image_name" ]] && docker image inspect "$image_name" >/dev/null 2>&1 \
  || fail 'a local SharipovAI image is required for offline backup'

volume_mount=$(docker volume inspect --format '{{.Mountpoint}}' "$volume_name" 2>/dev/null || true)
[[ "$volume_mount" == /* && -d "$volume_mount" ]] || fail 'persistent data volume mountpoint could not be resolved safely'
source_bytes=''
if source_bytes=$(run_low_priority timeout --foreground --kill-after=5s "${SIZE_PROBE_TIMEOUT_SECONDS}s" \
  du --apparent-size -s -B1 --one-file-system -- "$volume_mount" | awk 'NR == 1 {print $1}'); then
  :
else
  fail 'persistent data size probe failed or timed out'
fi
[[ "$source_bytes" =~ ^[0-9]+$ ]] || fail 'persistent data size probe returned an invalid value'
require_free_space "$((source_bytes * 2))" 'before staging persistent data'

if run_low_priority timeout --foreground --kill-after=10s "${HELPER_TIMEOUT_SECONDS}s" \
  docker run --rm -i \
    --name "$helper_name" \
    --label 'com.sharipovai.role=backup-helper' \
    --label "com.sharipovai.run=$run_id" \
    --no-healthcheck \
    --network none \
    --user 0:0 \
    --read-only \
    --security-opt no-new-privileges:true \
    --cap-drop ALL \
    --cap-add DAC_READ_SEARCH \
    -v "$volume_name:/source:ro" \
    -v "$work/data:/backup" \
    --entrypoint python \
    "$image_name" - "$source_mode" <<'PY'
import shutil
import sqlite3
import sys
from pathlib import Path

source = Path("/source")
destination = Path("/backup")
source_mode = sys.argv[1]
if source.is_symlink() or not source.is_dir():
    raise RuntimeError("persistent data source must be a real directory")
for path in source.rglob("*"):
    if path.is_symlink():
        raise RuntimeError(f"data symlink is forbidden in backup: {path.relative_to(source)}")
    if not (path.is_dir() or path.is_file()):
        raise RuntimeError(f"unsupported data entry in backup: {path.relative_to(source)}")

sqlite_suffixes = (".db", ".sqlite", ".sqlite3")

for item in source.iterdir():
    # SQLite databases are copied only below through SQLite's backup API. A
    # plain copy of an active database is not a verified snapshot.
    if item.suffix.lower() in sqlite_suffixes or item.name.endswith(("-wal", "-shm")):
        continue
    target = destination / item.name
    if item.is_dir():
        shutil.copytree(item, target, dirs_exist_ok=True)
    elif item.is_file():
        shutil.copy2(item, target)

# The source volume stays read-only. SQLite's backup API produces a consistent
# snapshot for every canonical top-level SQLite database.
for db in sorted(source.iterdir()):
    if db.suffix.lower() not in sqlite_suffixes:
        continue
    target_db = destination / db.name
    with sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True) as src, sqlite3.connect(target_db) as dst:
        src.backup(dst)
        result = dst.execute("PRAGMA quick_check").fetchone()
        if not result or result[0] != "ok":
            raise RuntimeError(f"database quick_check failed: {db.name}: {result!r}")
PY
then
  :
else
  helper_rc=$?
  cleanup_backup_helper
  fail "backup helper failed or exceeded ${HELPER_TIMEOUT_SECONDS}s (exit=$helper_rc)"
fi

run_low_priority python3 - "$work" "$source_mode" <<'PY'
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

root = Path(sys.argv[1])
source_mode = sys.argv[2]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


files = []
for path in sorted((root / "data").rglob("*")):
    if path.is_symlink():
        raise RuntimeError(f"backup symlink is forbidden: {path}")
    if path.is_file():
        files.append({
            "path": path.relative_to(root / "data").as_posix(),
            "bytes": path.stat().st_size,
            "sha256": sha256_file(path),
        })
if not files:
    raise RuntimeError("backup contains no files")
manifest = {
    "schema": 1,
    "created_at": datetime.now(timezone.utc).isoformat(),
    "files": files,
    "file_count": len(files),
    "source": "vps",
    "source_mode": source_mode,
}
(root / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
PY

staged_bytes=''
if staged_bytes=$(run_low_priority du --apparent-size -s -B1 -- "$work" | awk 'NR == 1 {print $1}'); then
  :
else
  fail 'staged backup size probe failed'
fi
[[ "$staged_bytes" =~ ^[0-9]+$ ]] || fail 'staged backup size probe returned an invalid value'
require_free_space "$staged_bytes" 'before archive creation'

archive_tmp=$(mktemp "$BACKUP_DIR/.sharipovai-$stamp.tar.gz.partial-XXXXXX")
archive_checksum_tmp="${archive_tmp}.sha256"
run_low_priority tar -C "$work" -czf "$archive_tmp" manifest.json data
if ! run_low_priority timeout --foreground --kill-after=5s "${SIZE_PROBE_TIMEOUT_SECONDS}s" \
  tar -tzf "$archive_tmp" >/dev/null; then
  fail 'backup archive integrity verification failed or timed out'
fi
archive_digest=$(run_low_priority sha256sum "$archive_tmp" | awk 'NR == 1 {print $1}')
[[ "$archive_digest" =~ ^[0-9a-fA-F]{64}$ ]] || fail 'archive SHA-256 generation failed'
printf '%s  %s\n' "$archive_digest" "$(basename "$archive")" >"$archive_checksum_tmp"
chmod 600 "$archive_tmp" "$archive_checksum_tmp"
mv "$archive_checksum_tmp" "$archive.sha256"
archive_checksum_tmp=''
if ! mv "$archive_tmp" "$archive"; then
  rm -f -- "$archive.sha256"
  fail 'atomic backup archive publication failed'
fi
archive_tmp=''
ln -sfn "$(basename "$archive")" "$BACKUP_DIR/latest.tar.gz"
ln -sfn "$(basename "$archive.sha256")" "$BACKUP_DIR/latest.tar.gz.sha256"

find "$BACKUP_DIR" -maxdepth 1 -type f -name 'sharipovai-*.tar.gz' -printf '%T@ %p\n' \
  | sort -rn | tail -n +$((KEEP + 1)) | cut -d' ' -f2- | while read -r old; do rm -f "$old" "$old.sha256"; done

log "backup completed using $source_mode"
echo "$archive"
