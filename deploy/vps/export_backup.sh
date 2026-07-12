#!/usr/bin/env bash
set -euo pipefail

APP_DIR=${APP_DIR:-/opt/sharipovai}
COMPOSE_DIR=${COMPOSE_DIR:-$APP_DIR/deploy/vps}
BACKUP_DIR=${BACKUP_DIR:-$COMPOSE_DIR/backups}
CONTAINER=${CONTAINER:-sharipovai}
KEEP=${KEEP:-7}

mkdir -p "$BACKUP_DIR"
chmod 700 "$BACKUP_DIR"
stamp=$(date -u +%Y%m%dT%H%M%SZ)
work="$BACKUP_DIR/.staging-$stamp"
archive="$BACKUP_DIR/sharipovai-$stamp.tar.gz"
mkdir -p "$work/data"
trap 'rm -rf "$work"' EXIT

cd "$COMPOSE_DIR"
docker compose ps --status running "$CONTAINER" | grep -q "$CONTAINER"

# Create a transactionally consistent SQLite copy inside the running container.
docker exec "$CONTAINER" python - <<'PY'
import os
import shutil
import sqlite3
from pathlib import Path

source = Path(os.getenv("SHARIPOVAI_DATA_DIR", "/var/lib/sharipovai"))
staging = source / ".backup-export"
if staging.exists():
    shutil.rmtree(staging)
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
docker cp "$container_id:/var/lib/sharipovai/.backup-export/." "$work/data/"
docker exec "$CONTAINER" rm -rf /var/lib/sharipovai/.backup-export

python3 - "$work" <<'PY'
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
root = Path(sys.argv[1])
files = []
for path in sorted((root / "data").rglob("*")):
    if path.is_file():
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        files.append({"path": path.relative_to(root / "data").as_posix(), "bytes": path.stat().st_size, "sha256": digest})
manifest = {"schema": 1, "created_at": datetime.now(timezone.utc).isoformat(), "files": files, "file_count": len(files), "source": "vps"}
(root / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
PY

tar -C "$work" -czf "$archive" manifest.json data
sha256sum "$archive" > "$archive.sha256"
ln -sfn "$(basename "$archive")" "$BACKUP_DIR/latest.tar.gz"
ln -sfn "$(basename "$archive.sha256")" "$BACKUP_DIR/latest.tar.gz.sha256"

find "$BACKUP_DIR" -maxdepth 1 -type f -name 'sharipovai-*.tar.gz' -printf '%T@ %p\n' \
  | sort -rn | tail -n +$((KEEP + 1)) | cut -d' ' -f2- | while read -r old; do rm -f "$old" "$old.sha256"; done

echo "$archive"
