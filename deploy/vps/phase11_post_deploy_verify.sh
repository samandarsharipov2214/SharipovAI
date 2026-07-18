#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="${SHARIPOVAI_ROOT:-/opt/sharipovai}"
OUT="${PHASE11_VERIFY_OUTPUT:-/var/lib/sharipovai/audit/phase11-post-deploy.json}"
HEALTH_URL="${SHARIPOVAI_HEALTH_URL:-http://127.0.0.1:8000/health}"
mkdir -p "$(dirname "$OUT")"
tmp="$(mktemp "${OUT}.XXXX")"
trap 'rm -f "$tmp"' EXIT
cd "$ROOT"
python -m compileall -q .
curl --fail --silent --show-error --max-time 10 "$HEALTH_URL" >/tmp/phase11-health.json
python - <<'PY' > "$tmp"
import json, os, sqlite3, time, urllib.request
from audit.phase11_production_audit import ProductionAudit
report=ProductionAudit('.').run()
report['verified_at_ms']=int(time.time()*1000)
report['http_health']=json.load(open('/tmp/phase11-health.json',encoding='utf-8'))
dsn=os.getenv('DATABASE_URL','')
if dsn.startswith('sqlite:///'):
    con=sqlite3.connect(dsn.removeprefix('sqlite:///'))
    report['database_quick_check']=con.execute('PRAGMA quick_check').fetchone()[0]
    con.close()
else:
    report['database_quick_check']='external_database_not_checked_by_sqlite_probe'
print(json.dumps(report,indent=2,sort_keys=True))
raise SystemExit(0 if report['status']=='ready_for_bounded_testnet_preflight' else 2)
PY
chmod 0640 "$tmp"
mv -f "$tmp" "$OUT"
echo "Phase 11 verification written to $OUT"
