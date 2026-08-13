#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

APP_DIR=${APP_DIR:-/opt/sharipovai-repo}
COMPOSE_DIR=${COMPOSE_DIR:-$APP_DIR/deploy/vps}
BACKUP_DIR=${BACKUP_DIR:-$COMPOSE_DIR/backups}
CONTAINER=${CONTAINER:-sharipovai}
KEEP=${KEEP:-7}

fail() { printf '[backup] ERROR: %s\n' "$*" >&2; exit 1; }
log() { printf '[backup] %s\n' "$*"; }

if ! [[ "$KEEP" =~ ^[0-9]+$ ]] || (( KEEP < 1 || KEEP > 100 )); then
  fail 'KEEP must be an integer between 1 and 100'
fi
mkdir -p "$BACKUP_DIR"
chmod 700 "$BACKUP_DIR"
exec 9>"$BACKUP_DIR/.export.lock"
if ! flock -n 9; then
  fail 'backup export is already running'
fi

stamp=$(date -u +%Y%m%dT%H%M%SZ)
work=$(mktemp -d "$BACKUP_DIR/.staging-$stamp-XXXXXX")
trap 'rm -rf "$work"' EXIT
archive="$BACKUP_DIR/sharipovai-$stamp.tar.gz"
if [[ -e "$archive" || -e "$archive.sha256" ]]; then
  fail "backup archive already exists for timestamp $stamp"
fi
mkdir -p "$work/data"

cd "$COMPOSE_DIR"
source_mode='stopped-volume-readonly'
container_id=$(docker compose ps -a -q "$CONTAINER" 2>/dev/null || true)
running='false'
if [[ -n "$container_id" ]]; then
  running=$(docker inspect --format '{{.State.Running}}' "$container_id" 2>/dev/null || printf 'false')
fi

if [[ "$running" == 'true' ]]; then
  source_mode='running-volume-readonly'
  log 'creating transactionally consistent backup through isolated read-only helper'
else
  log 'application container is stopped; creating read-only backup directly from persistent volume'
fi


  rendered=$(mktemp)
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

  if [[ -n "$container_id" ]]; then
    detected_volume=$(docker inspect --format '{{range .Mounts}}{{if eq .Destination "/var/lib/sharipovai"}}{{.Name}}{{end}}{{end}}' "$container_id" 2>/dev/null || true)
    detected_image=$(docker inspect --format '{{.Config.Image}}' "$container_id" 2>/dev/null || true)
    [[ -n "$detected_volume" ]] && volume_name=$detected_volume
    [[ -n "$detected_image" ]] && image_name=$detected_image
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

  docker run --rm -i \
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
import os
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
    # SQLite databases are copied only below through SQLite's backup API.  A
    # plain copy of an active database (even if the WAL/SHM files are omitted)
    # is not a verified snapshot.
    if item.suffix.lower() in sqlite_suffixes or item.name.endswith(("-wal", "-shm")):
        continue
    target = destination / item.name
    if item.is_dir():
        shutil.copytree(item, target, dirs_exist_ok=True)
    elif item.is_file():
        shutil.copy2(item, target)

# The source volume stays read-only. SQLite's backup API produces a consistent
# snapshot for every canonical top-level SQLite database without copying a
# running database's WAL/SHM files.
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

python3 - "$work" "$source_mode" <<'PY'
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

root = Path(sys.argv[1])
source_mode = sys.argv[2]
files = []
for path in sorted((root / "data").rglob("*")):
    if path.is_symlink():
        raise RuntimeError(f"backup symlink is forbidden: {path}")
    if path.is_file():
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        files.append({
            "path": path.relative_to(root / "data").as_posix(),
            "bytes": path.stat().st_size,
            "sha256": digest,
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

tar -C "$work" -czf "$archive" manifest.json data
sha256sum "$archive" > "$archive.sha256"
ln -sfn "$(basename "$archive")" "$BACKUP_DIR/latest.tar.gz"
ln -sfn "$(basename "$archive.sha256")" "$BACKUP_DIR/latest.tar.gz.sha256"

find "$BACKUP_DIR" -maxdepth 1 -type f -name 'sharipovai-*.tar.gz' -printf '%T@ %p\n' \
  | sort -rn | tail -n +$((KEEP + 1)) | cut -d' ' -f2- | while read -r old; do rm -f "$old" "$old.sha256"; done

log "backup completed using $source_mode"
echo "$archive"
