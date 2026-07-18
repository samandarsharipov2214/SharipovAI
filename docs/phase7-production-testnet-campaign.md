# Phase 7 — Production Stabilization and First Bounded Testnet Campaign

Status: **implementation ready for CI and staged VPS deployment. Real campaign completion is not claimed until authenticated private execution evidence proves every completion gate.**

Phase 7 adds an operational layer around the existing canonical campaign and execution services. It does not introduce a second order path, a raw order API or any Mainnet capability.

## Delivered

- Target-commit VPS preflight before backup or code replacement.
- SQLite header and `PRAGMA quick_check` validation.
- Minimum free-disk guard and secret-file permission validation.
- Non-root Docker image, build-time `pip check`/`compileall`, healthchecks, graceful shutdown, bounded logs, dropped capabilities and `no-new-privileges`.
- Permanent production-safe Compose plus a separate explicit bounded-Testnet overlay.
- Fail-closed environment validation that rejects Mainnet credentials and Testnet notional above 25 USDT.
- Verified backup, post-deploy smoke checks and automatic restoration of production-safe Compose on a failed Testnet transition.
- Finite, resumable first-campaign runner with cycle/time limits and an append-only evidence bundle.
- Persistent, deduplicated critical alerts with automatic resolution history.
- Optional sanitized HTTPS webhook and Telegram alert delivery.
- Three-second responsive Dashboard polling for progress, heartbeat, alerts, actual private fills and actual fees.
- Atomic JSON export after the canonical immutable final report exists.

## Authority boundary

The only campaign launch path remains `CampaignOperationsService.start_first_testnet_campaign` through the existing admin API or canonical operator tooling.

Phase 7 components cannot:

- write or discover credentials;
- alter Mainnet compile state;
- submit a raw order;
- bypass candidate validation, hard risk, idempotency or reconciliation;
- fabricate fills, fees or reports;
- auto-promote a campaign;
- treat a failed/queued/skipped CI result as approval.

## Permanent production-safe environment

The permanent VPS file is:

```text
deploy/vps/.env.vps
```

It must retain mode `0600` and these locks:

```env
EXCHANGE_MODE=sandbox
EXCHANGE_BASE_URL=https://api-testnet.bybit.com
EXCHANGE_LIVE_TRADING_ENABLED=0
FEATURE_BYBIT_LIVE_EXECUTION=0
EXECUTION_KILL_SWITCH=1
TESTNET_EXECUTION_ENABLED=0
AUTONOMOUS_TESTNET_ENABLED=0
AUTONOMOUS_TESTNET_BRIDGE_ENABLED=0
FEATURE_BYBIT_TESTNET=0
FEATURE_BYBIT_PRIVATE_ORDER_WS=0
RUNTIME_FILL_HARVESTER_ENABLED=0
SCHEDULED_CAMPAIGN_ORCHESTRATOR_ENABLED=0
PHASE6_TESTNET_RELEASE_GATE=blocked
EXECUTION_MAX_NOTIONAL_USDT=25
SHADOW_TESTNET_MAX_NOTIONAL_USDT=25
```

Testnet credentials and the green release gate are forbidden in the permanent production file.

## Isolated bounded-Testnet overlay

Create a separate ignored file only for the authorized campaign window:

```bash
cd /opt/sharipovai-repo/deploy/vps
cp .env.testnet-campaign.example .env.testnet-campaign
chmod 600 .env.testnet-campaign
```

Set only the isolated Testnet authorization:

```env
PHASE6_TESTNET_RELEASE_GATE=green
BYBIT_TESTNET_API_KEY=<isolated-testnet-key>
BYBIT_TESTNET_API_SECRET=<isolated-testnet-secret>
```

The key must be Testnet-only and must not permit withdrawals or transfers.

Validate both modes without starting execution:

```bash
python3 validate_runtime_env.py \
  --env-file .env.vps \
  --mode production

python3 validate_runtime_env.py \
  --env-file .env.vps \
  --env-file .env.testnet-campaign \
  --mode testnet-campaign
```

## Production deployment sequence

Deploy the exact reviewed target through the protected updater:

```bash
cd /opt/sharipovai-repo
sudo APP_DIR=/opt/sharipovai-repo bash deploy/vps/update_from_main.sh
```

Deployment order:

```text
fetch immutable target
  -> target preflight
  -> verified backup
  -> checkout exact target
  -> render and validate production-safe Compose
  -> build candidate
  -> replace services
  -> health endpoint
  -> container health
  -> database health
  -> rollback on any failure
```

Verify after deployment:

```bash
sudo bash deploy/vps/smoke_check.sh production
```

The preflight and smoke check are evidence, not substitutes for complete green required CI.

## Enter the finite Testnet window

After current-head CI is green and the isolated overlay is ready:

```bash
sudo bash deploy/vps/testnet_campaign_deploy.sh \
  I_APPROVE_BOUNDED_TESTNET_RUNTIME_DEPLOYMENT
```

The transition:

1. validates the merged env without shell-sourcing secrets;
2. runs Phase 7 VPS preflight;
3. creates a verified backup;
4. renders the explicit Testnet Compose override;
5. recreates the application container;
6. validates health, rendered financial locks and database state;
7. restores production-safe Compose on any error.

Expected success marker:

```text
TESTNET_RUNTIME_READY ... mainnet=false max_notional_usdt=25
```

This transition only exposes the existing audited bounded-Testnet path. It does not start a campaign.

## Readiness plan

```bash
docker exec sharipovai python scripts/testnet_campaignctl.py plan \
  --experiment-id '<promoted-experiment-id>' \
  --confirmation I_APPROVE_BOUNDED_TESTNET_SHADOW_CAMPAIGN
```

Proceed only with:

```json
{
  "status": "ready",
  "can_start": true,
  "blockers": []
}
```

Mandatory evidence includes isolated Testnet credentials, authenticated private `order` and `execution` topics, restart-safe reconciliation, one manually promoted experiment and zero active campaigns.

## Finite first-campaign runner

Run one campaign to terminal evidence or a hard operator limit:

```bash
docker exec sharipovai python scripts/first_testnet_campaign.py \
  --experiment-id '<promoted-experiment-id>' \
  --scope BTCUSDT \
  --actor '<authenticated-operator>' \
  --max-cycles 240 \
  --interval-seconds 15 \
  --timeout-seconds 14400 \
  --output-dir /var/lib/sharipovai/evidence/testnet-campaigns \
  --start-confirmation I_APPROVE_BOUNDED_TESTNET_SHADOW_CAMPAIGN \
  --cycle-confirmation I_APPROVE_BOUNDED_TESTNET_CAMPAIGN_CYCLE \
  --report-confirmation I_APPROVE_IMMUTABLE_CAMPAIGN_REPORT
```

The runner exits `0` only when `real_fill_evidence_confirmed=true`. Every blocked, incomplete, timed-out or interrupted result exits `2` and retains evidence.

Resume only the same non-terminal campaign:

```bash
docker exec sharipovai python scripts/first_testnet_campaign.py \
  --experiment-id '<promoted-experiment-id>' \
  --resume-campaign-id '<campaign-id>' \
  --scope BTCUSDT \
  --actor '<authenticated-operator>' \
  --output-dir /var/lib/sharipovai/evidence/testnet-campaigns \
  --start-confirmation I_APPROVE_BOUNDED_TESTNET_SHADOW_CAMPAIGN \
  --cycle-confirmation I_APPROVE_BOUNDED_TESTNET_CAMPAIGN_CYCLE \
  --report-confirmation I_APPROVE_IMMUTABLE_CAMPAIGN_REPORT
```

Resume cannot bypass any blocker except the expected `no_active_campaign` gate caused by that same running campaign.

## Evidence bundle

```text
/var/lib/sharipovai/evidence/testnet-campaigns/
├── launch-plan.json
└── <campaign-id>/
    ├── campaign-start.json
    ├── campaign-latest.json
    ├── cycles.jsonl
    ├── final-promotion-report.json
    ├── operations-final.json
    └── runner-result.json
```

The bundle supplements the canonical `ProjectDatabase`; it does not replace it.

## Monitoring and critical alerts

Dashboard/API:

```text
GET  /api/campaigns/phase7/monitor?refresh=true
GET  /api/campaigns/phase7/fills
GET  /api/campaigns/phase7/report
GET  /api/campaigns/phase7/alerts
POST /api/campaigns/phase7/alerts/refresh
```

Persistent critical alert signals:

- more than one non-terminal campaign;
- kill switch engaged during an active campaign;
- non-restart-safe startup/execution reconciliation;
- stale or unavailable private execution stream;
- stale Phase 7 monitor heartbeat;
- blocked campaign;
- orphan, duplicate, unresolved, reconciliation or notional evidence failure;
- orchestrator errors.

Configure optional external delivery in `.env.vps`:

```env
CRITICAL_ALERT_MONITOR_ENABLED=1
CRITICAL_ALERT_MONITOR_SECONDS=15
CRITICAL_ALERT_REPEAT_SECONDS=900
ALERT_DELIVERY_ENABLED=1
ALERT_TELEGRAM_CHAT_ID=<chat-id>
ALERT_WEBHOOK_URL=https://<trusted-endpoint>
```

Telegram delivery also uses `BOT_TOKEN`. Non-HTTPS webhook URLs are rejected. Delivery failures never erase persisted alert evidence.

## Completion definition

A start response, accepted order response, screenshot, Dashboard progress bar, synthetic fixture or copied JSON is not campaign completion.

Completion requires all of the following at the same evidence revision:

- at least 20 matched Paper/Testnet fills;
- each accepted order within 10–25 USDT notional;
- zero unmatched Paper fills;
- zero unmatched Testnet fills;
- zero orphan executions;
- zero duplicate or conflicting identities;
- zero unresolved intents/orders;
- actual private execution fees;
- fresh authenticated private order and execution streams;
- restart-safe startup and execution reconciliation;
- canonical final promotion report generated;
- separate manual decision remains required.

## Close the execution window

After completion, block, timeout, alert or operator abort:

```bash
sudo bash deploy/vps/testnet_campaign_stop.sh \
  I_APPROVE_RESTORE_PRODUCTION_KILL_SWITCH
```

Expected marker:

```text
PRODUCTION_LOCKS_RESTORED kill_switch=1 testnet_execution=0 mainnet=false
```

Then securely remove or rotate the Testnet overlay secret.

## Immediate abort conditions

Restore production-safe mode immediately on:

- orphan, duplicate, unresolved or conflicting identity;
- stale private stream or monitor heartbeat;
- failed startup/execution reconciliation;
- notional outside 10–25 USDT;
- missing actual fee evidence;
- ambiguous exchange outcome;
- more than one active campaign;
- unexpected production exchange URL or any Mainnet credential;
- required CI no longer green;
- unexplained critical alert.

Never fabricate a fill, patch canonical financial evidence manually or blind-retry an ambiguous request.

## Truth rule

Until the private execution store contains 20+ campaign-bound fills and the canonical final report exists, the only truthful status is:

```text
Campaign implementation ready; real bounded campaign not yet completed.
```
