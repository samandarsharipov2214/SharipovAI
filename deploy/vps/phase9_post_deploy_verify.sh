#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="${SHARIPOVAI_ROOT:-/opt/sharipovai-repo}"
COMPOSE="${PHASE9_COMPOSE_FILE:-$ROOT/deploy/vps/docker-compose.yml}"
REPORT="${PHASE9_VERIFY_REPORT:-/var/lib/sharipovai/deploy/phase9-verify.json}"
mkdir -p "$(dirname "$REPORT")"

cd "$ROOT"
docker compose -f "$COMPOSE" config --quiet
docker compose -f "$COMPOSE" ps --format json >/tmp/phase9-compose-ps.json
python3 -m compileall -q campaigns dashboard observability scripts
python3 - <<'PY'
import json, os, sqlite3, time, urllib.request
url=os.getenv('PHASE9_HEALTH_URL','http://127.0.0.1:8000/health')
with urllib.request.urlopen(url, timeout=10) as response:
    if response.status != 200: raise SystemExit(f'health status {response.status}')
db=os.getenv('SHARIPOVAI_DB_PATH','/var/lib/sharipovai/sharipovai.db')
with sqlite3.connect(db) as conn:
    result=conn.execute('PRAGMA quick_check').fetchone()[0]
    if result != 'ok': raise SystemExit(f'database quick_check={result}')
report={'status':'ok','checked_at_ms':int(time.time()*1000),'health_url':url,'database':db,'mainnet_enabled':False}
target=os.getenv('PHASE9_VERIFY_REPORT','/var/lib/sharipovai/deploy/phase9-verify.json')
with open(target+'.tmp','w',encoding='utf-8') as fh: json.dump(report,fh,sort_keys=True,indent=2)
os.replace(target+'.tmp',target)
print(json.dumps(report,sort_keys=True))
PY
