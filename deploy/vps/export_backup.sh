#!/usr/bin/env bash
set -euo pipefail
umask 077

APP_DIR=${APP_DIR:-/opt/sharipovai}
COMPOSE_DIR=${COMPOSE_DIR:-$APP_DIR/deploy/vps}
BACKUP_DIR=${BACKUP_DIR:-$COMPOSE_DIR/backups}
CONTAINER=${CONTAINER:-sharipovai}
KEEP=${KEEP:-7}

if ! [[ "$KEEP" =~ ^[0-9]+$ ]] || (( KEEP < 1 || KEEP > 100 )); then
  echo "KEEP must be an integer between 1 and 100" >&2
  exit 1
fi
mkdir -p "$BACKUP_DIR"
chmod 700 "$BACKUP_DIR"
exec 9>"$BACKUP_DIR/.export.lock"
if ! flock -n 9; then
  echo "backup export is already running" >&2
  exit 1
fi

stamp=$(date -u +%Y%m%dT%H%M%SZ)
work=$(mktemp -d "$BACKUP_DIR/.staging-$stamp-XXXXXX")
trap 'rm -rf "$work"' EXIT
archive="$BACKUP_DIR/sharipovai-$stamp.tar.gz"
if [[ -e "$archive" || -e "$archive.sha256" ]]; then
  echo "backup archive already exists for timestamp $stamp" >&2
  exit 1
fi
mkdir -p "$work/data"

cd "$COMPOSE_DIR"
docker compose ps --status running "$CONTAINER" | grep -q "$CONTAINER"

# Create a transactionally consistent SQLite copy inside the running container.
docker exec -i "$CONTAINER" python - <<'PY'
import os
import shutil
import sqlite3
from pathlib import Path

source = Path(os.getenv("SHARIPOVAI_DATA_DIR", "/var/lib/sharipovai"))
staging = source / ".backup-export"
if staging.exists():
    shutil.rmtree(staging)
if source.is_symlink() or not source.is_dir():
    raise RuntimeError("data directory must be a real directory")
for path in source.rglob("*"):
    if path == staging or staging in path.parents:
        continue
    if path.is_symlink():
        raise RuntimeError(f"data symlink is forbidden in backup: {path.relative_to(source)}")
staging.mkdir(parents=True)
for item in source.iterdir():
    if item.name == staging.name:
        continue
    if item.is_dir():
        shutil.copytree(item, staging / item.name)
    elif item.name != "sharipovai_shared.db" and not item.name.endswith(("-wal", "-shm")):
        shutil.copy2(item, staging / item.name)
db = source / "sharipovai_shared.db"
if db.exists():
    with sqlite3.connect(db) as src, sqlite3.connect(staging / db.name) as dst:
        src.backup(dst)
PY

container_id=$(docker compose ps -q "$CONTAINER")
container_data_dir=$(docker exec "$CONTAINER" sh -c 'printf "%s" "${SHARIPOVAI_DATA_DIR:-/var/lib/sharipovai}"')
if [[ "$container_data_dir" != /* || "$container_data_dir" == *$'\n'* || "$container_data_dir" == *'/../'* ]]; then
  echo "container data directory is unsafe" >&2
  exit 1
fi
docker cp "$container_id:$container_data_dir/.backup-export/." "$work/data/"
docker exec "$CONTAINER" rm -rf "$container_data_dir/.backup-export"

python3 - "$work" <<'PY'
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

root = Path(sys.argv[1])
files = []
for path in sorted((root / "data").rglob("*")):
    if path.is_symlink():
        raise RuntimeError(f"backup symlink is forbidden: {path}")
    if path.is_file():
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        files.append({"path": path.relative_to(root / "data").as_posix(), "bytes": path.stat().st_size, "sha256": digest})
if not files:
    raise RuntimeError("backup contains no files")
manifest = {
    "schema": 1,
    "created_at": datetime.now(timezone.utc).isoformat(),
    "files": files,
    "file_count": len(files),
    "source": "vps",
}
(root / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
PY

tar -C "$work" -czf "$archive" manifest.json data
sha256sum "$archive" > "$archive.sha256"
ln -sfn "$(basename "$archive")" "$BACKUP_DIR/latest.tar.gz"
ln -sfn "$(basename "$archive.sha256")" "$BACKUP_DIR/latest.tar.gz.sha256"

find "$BACKUP_DIR" -maxdepth 1 -type f -name 'sharipovai-*.tar.gz' -printf '%T@ %p\n' \
  | sort -rn | tail -n +$((KEEP + 1)) | cut -d' ' -f2- | while read -r old; do rm -f "$old" "$old.sha256"; done

echo "$archive"
