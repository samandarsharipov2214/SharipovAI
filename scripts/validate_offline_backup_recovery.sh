#!/usr/bin/env bash
set -Eeuo pipefail

sandbox="$(mktemp -d)"
cleanup() {
  docker compose --project-directory "$sandbox/compose" -f "$sandbox/compose/docker-compose.yml" down -v --remove-orphans >/dev/null 2>&1 || true
  sudo rm -rf "$sandbox"
}
trap cleanup EXIT
mkdir -p "$sandbox/compose" "$sandbox/backups"
cat >"$sandbox/compose/docker-compose.yml" <<'YAML'
services:
  sharipovai:
    image: python:3.12-slim
    command: ["python", "-c", "print('not started')"]
    volumes:
      - sharipovai_data:/var/lib/sharipovai
volumes:
  sharipovai_data:
YAML

docker pull -q python:3.12-slim >/dev/null
volume_name="$(docker compose --project-directory "$sandbox/compose" \
  -f "$sandbox/compose/docker-compose.yml" config --format json \
  | python -c 'import json,sys; print(json.load(sys.stdin)["volumes"]["sharipovai_data"]["name"])')"

docker run --rm -i --user 0:0 \
  -v "$volume_name:/var/lib/sharipovai" \
  python:3.12-slim python - <<'PY'
import sqlite3
from pathlib import Path
root = Path('/var/lib/sharipovai')
root.mkdir(parents=True, exist_ok=True)
(root / 'marker.json').write_text('{"state":"preserved"}', encoding='utf-8')
with sqlite3.connect(root / 'sharipovai_shared.db') as db:
    db.execute('create table evidence (id integer primary key, value text not null)')
    db.execute('insert into evidence(value) values (?)', ('offline-backup-ok',))
    db.commit()
PY

sudo env \
  APP_DIR="$GITHUB_WORKSPACE" \
  COMPOSE_DIR="$sandbox/compose" \
  BACKUP_DIR="$sandbox/backups" \
  KEEP=2 \
  bash deploy/vps/export_backup.sh

archive="$(readlink -f "$sandbox/backups/latest.tar.gz")"
sudo tar -C "$sandbox" -xzf "$archive"
sudo chown -R "$(id -u):$(id -g)" "$sandbox/data" "$sandbox/manifest.json"
python - "$sandbox" <<'PY'
import json
import sqlite3
import sys
from pathlib import Path
root = Path(sys.argv[1])
manifest = json.loads((root / 'manifest.json').read_text(encoding='utf-8'))
assert manifest['source_mode'] == 'stopped-volume-readonly', manifest
assert manifest['file_count'] >= 2, manifest
assert json.loads((root / 'data' / 'marker.json').read_text(encoding='utf-8')) == {'state': 'preserved'}
with sqlite3.connect(root / 'data' / 'sharipovai_shared.db') as db:
    assert db.execute('pragma quick_check').fetchone() == ('ok',)
    assert db.execute('select value from evidence').fetchone() == ('offline-backup-ok',)
PY

docker run --rm -i --user 0:0 \
  -v "$volume_name:/var/lib/sharipovai:ro" \
  python:3.12-slim python - <<'PY'
import json
import sqlite3
from pathlib import Path
root = Path('/var/lib/sharipovai')
assert json.loads((root / 'marker.json').read_text(encoding='utf-8')) == {'state': 'preserved'}
assert not (root / '.backup-export').exists()
with sqlite3.connect(f'file:{root / "sharipovai_shared.db"}?mode=ro', uri=True) as db:
    assert db.execute('pragma quick_check').fetchone() == ('ok',)
PY

echo OFFLINE_BACKUP_RECOVERY_OK
