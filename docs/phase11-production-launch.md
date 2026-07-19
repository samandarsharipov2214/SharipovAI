# Phase 11 Production and First Bounded Testnet Launch

Status: **operator runbook; no launch is implied by this document.**

Mainnet execution remains compiled out. The first campaign remains bounded to
`10–25 USDT` per accepted order and is not successful until at least 20 actual
matched Paper/Testnet fills, actual private fees and zero identity failures are
persisted.

## State model

| State | Execution flags | Kill switch | Allowed work |
| --- | --- | --- | --- |
| `production_safe` | Testnet and live off | on | audit, dashboard, research |
| `release_verified` | Testnet and live off | on | deployment verification |
| `bounded_testnet_window` | approved Testnet flags on | off for finite window | one authorized campaign |
| `production_restored` | Testnet and live off | on | reporting and review |

Application code cannot move between these states. Only the reviewed VPS scripts
and exact operator confirmations may do so.

## 1. Merge gate

Do not deploy while any required workflow is queued, skipped, cancelled or failed.
The exact merged commit must have complete green:

```text
Tests
Project Guardrails
Dashboard Stabilization
Phase 11 Hardening
Проверка SharipovAI
```

Record the merged SHA:

```bash
export SHARIPOVAI_EXPECTED_SHA='<40-character-merged-sha>'
```

## 2. Canonical checkout

The production checkout is:

```text
/opt/sharipovai-repo
```

All Phase 11 scripts use this path by default and also accept an explicit
`APP_DIR` or `SHARIPOVAI_ROOT`. Multiple independent production checkouts are
forbidden.

## 3. Production-safe preflight

The following command requires execution flags off, kill switch on, auth material,
canonical database, exact SHA and a clean worktree:

```bash
cd /opt/sharipovai-repo
sudo -E APP_DIR=/opt/sharipovai-repo \
  SHARIPOVAI_EXPECTED_SHA="$SHARIPOVAI_EXPECTED_SHA" \
  bash deploy/vps/phase11_release_preflight.sh
```

Expected terminal marker:

```text
PHASE11_PREFLIGHT_OK
```

Any other result blocks deployment.

## 4. Deploy exact reviewed SHA

Use the existing locked updater. It creates a verified backup and automatically
restores the previous SHA when health does not recover:

```bash
sudo APP_DIR=/opt/sharipovai-repo \
  BRANCH=main \
  bash /opt/sharipovai-repo/deploy/vps/update_from_main.sh
```

Confirm:

```bash
git -C /opt/sharipovai-repo rev-parse HEAD
```

The result must equal `SHARIPOVAI_EXPECTED_SHA` exactly.

## 5. Post-deploy evidence

```bash
sudo -E APP_DIR=/opt/sharipovai-repo \
  SHARIPOVAI_EXPECTED_SHA="$SHARIPOVAI_EXPECTED_SHA" \
  bash /opt/sharipovai-repo/deploy/vps/phase11_post_deploy_verify.sh
```

The immutable evidence file is:

```text
/var/lib/sharipovai/audit/phase11-post-deploy.json
```

Required values:

```text
status = ready_for_bounded_testnet_preflight
blockers = []
database_health.status = ok
http_health.status = ok
deployed_sha = SHARIPOVAI_EXPECTED_SHA
mainnet_enabled = false
automatic_campaign_launch = false
```

## 6. Monitoring installation

```bash
sudo APP_DIR=/opt/sharipovai-repo \
  bash /opt/sharipovai-repo/deploy/vps/install_phase10_monthly_monitor.sh
```

Verify:

```bash
systemctl is-enabled sharipovai-monthly-performance.timer
systemctl is-active sharipovai-monthly-performance.timer
systemctl list-timers sharipovai-monthly-performance.timer --no-pager
```

## 7. Prepare isolated Testnet credentials

Create `/opt/sharipovai-repo/deploy/vps/.env.testnet-campaign` from the example,
set mode `0600`, use an isolated Bybit Testnet key and disable withdrawal/transfer
permissions. Mainnet credentials must not be present in the campaign runtime.

Validate before changing runtime state:

```bash
python3 /opt/sharipovai-repo/deploy/vps/validate_runtime_env.py \
  --env-file /opt/sharipovai-repo/deploy/vps/.env.vps \
  --env-file /opt/sharipovai-repo/deploy/vps/.env.testnet-campaign \
  --mode testnet-campaign
```

## 8. Enter the finite Testnet window

```bash
sudo APP_DIR=/opt/sharipovai-repo \
  TESTNET_CAMPAIGN_MAX_WINDOW_SECONDS=14400 \
  bash /opt/sharipovai-repo/deploy/vps/testnet_campaign_deploy.sh \
  I_APPROVE_BOUNDED_TESTNET_RUNTIME_DEPLOYMENT
```

The deploy script arms the automatic production-lock restoration timer. Verify it:

```bash
systemctl is-active sharipovai-testnet-auto-stop.timer
```

## 9. Machine launch checklist

Run this **inside the bounded Testnet container** before starting a campaign:

```bash
docker exec \
  -e SHARIPOVAI_EXPECTED_SHA="$SHARIPOVAI_EXPECTED_SHA" \
  sharipovai \
  python scripts/phase11_first_campaign_checklist.py \
    --experiment-id '<approved-experiment-id>' \
    --expected-sha "$SHARIPOVAI_EXPECTED_SHA" \
    --audit-file /var/lib/sharipovai/audit/phase11-post-deploy.json \
    --output /var/lib/sharipovai/evidence/phase11-first-campaign-readiness.json
```

Proceed only with:

```text
status = ready
ready = true
failed_checks = []
campaign_started = false
mainnet_enabled = false
```

The checklist is read-only. It cannot start a campaign or alter flags.

## 10. Start and collect real evidence

Follow `docs/first-real-testnet-campaign.md`. The finite operator process must retain
partial evidence on timeout or failure. A campaign database row, REST acceptance,
Paper-only fill, screenshot or copied JSON is not execution proof.

Completion requires:

- 20 or more actual matched Paper/Testnet fills;
- actual authenticated private `execId` evidence;
- actual fee amount and currency;
- zero orphan, duplicate, conflicting, unmatched or unresolved identities;
- fresh private `order` and `execution` streams;
- restart-safe reconciliation;
- immutable final report eligible for a separate manual decision.

## 11. Immediate abort

Abort immediately on stale stream, private auth loss, unknown submission outcome,
identity conflict, orphan fill, quantity mismatch, missing fee, order above 25 USDT,
multiple campaigns, database failure or unexplained critical alert.

Restore production-safe state:

```bash
sudo bash /opt/sharipovai-repo/deploy/vps/testnet_campaign_stop.sh \
  I_APPROVE_RESTORE_PRODUCTION_KILL_SWITCH
```

Confirm Testnet flags off and kill switch on with production smoke checks.

## 12. Exact-SHA rollback

Rollback is allowed only to a known ancestor full SHA:

```bash
export SHARIPOVAI_EXPECTED_SHA='<current-deployed-sha>'
export SHARIPOVAI_ROLLBACK_SHA='<reviewed-ancestor-sha>'

sudo -E APP_DIR=/opt/sharipovai-repo \
  bash /opt/sharipovai-repo/deploy/vps/phase11_rollback.sh \
  I_APPROVE_PHASE11_EXACT_SHA_ROLLBACK
```

The rollback script locks deployment, validates ancestry, runs target preflight,
backs up the current release with the current trusted exporter, verifies financial
locks, rebuilds, checks health and smoke tests, and restores the original SHA if the
rollback target fails.

## 13. After campaign

Always close the Testnet window before analysis. Generate Phase 8 analysis, immutable
Phase 9 report and Phase 10 performance snapshot. Scaling remains prohibited until at
least two clean campaigns satisfy all gates and a separate expiring Testnet-only
scaling authority is manually approved.
