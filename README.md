# SharipovAI OS

SharipovAI is a safety-first AI trading operating system for verified market evidence, deterministic risk, Paper execution and bounded Bybit Testnet campaigns.

> Production truth: live execution remains unavailable. Production boots with the kill switch engaged. Testnet writes exist only in explicitly authorized finite windows. Phase 11 adds audit and readiness controls; it does not claim a completed real campaign or profitable execution.

## Phase 11

Delivered:

- deterministic production audit with blockers, warnings and SHA-256 evidence;
- checks for live-execution locks, kill switch, secret hygiene, required assets and the 50 USDT Testnet ceiling;
- admin-only production audit and readiness APIs;
- consolidated Production Overview dashboard;
- persistent dark/light theme and five-second visibility-aware refresh;
- mobile and reduced-motion UI contracts;
- fail-closed release preflight;
- atomic post-deploy verification with HTTP health and database integrity;
- focused regression tests and a production runbook;
- all Phase 7-10 campaign, scaling, performance and risk controls retained.

## API

```text
GET /api/production/phase11/audit
GET /api/production/phase11/overview
```

The routes are admin-only and read-only.

## Final preflight

```bash
sudo -E bash deploy/vps/phase11_release_preflight.sh
```

## Post-deploy verification

```bash
sudo -E bash deploy/vps/phase11_post_deploy_verify.sh
```

Evidence is atomically written to `/var/lib/sharipovai/audit/phase11-post-deploy.json`.

## Verification

```bash
python -m pip install -r requirements-dev.txt
python -m pip check
python -m compileall -q .
python -m pytest tests/test_phase11_production_audit.py tests/test_phase11_dashboard_contract.py -q --tb=short
python -m pytest -q --tb=short
```

## Documentation

- `CONSTITUTION.md`
- `docs/phase10-controlled-scaling-performance.md`
- `docs/phase11-full-production-audit.md`

## Truth rule

SharipovAI does not promise profit and does not fabricate campaign completion, fills, fees, PnL, alert delivery, scaling execution, deployment success or readiness. Missing, queued, skipped or failed evidence is not approval.
