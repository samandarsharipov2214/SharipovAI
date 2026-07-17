# Phase 7 — Production Readiness and First Campaign Operations

Status: **implementation ready for CI and staged VPS deployment; real Testnet evidence is not claimed until the runner records authenticated private fills.**

Phase 7 turns the existing campaign state machine into an operable production control plane without creating a new order path or weakening the Mainnet compile lock.

## Delivered control plane

| Area | Production contract |
| --- | --- |
| Docker | non-root image, `tini`, healthcheck, bounded logs, dropped capabilities and `no-new-privileges` |
| VPS deployment | production-safe base Compose, isolated Testnet overlay, env validation, backup, smoke test and automatic rollback |
| Campaign execution | one bounded campaign runner, explicit confirmations, finite cycle/time limits and persistent evidence bundle |
| Alerting | persistent deduplicated alerts for kill switch, reconciliation, private stream, blocker and orchestrator failures |
| Dashboard | responsive campaign selector, live progress, alert controls, gates, schedules, history and operator actions |
| Evidence | JSON/JSONL files plus immutable canonical database records; no synthetic fills |

## Runtime files

Production-safe configuration:

```text
deploy/vps/.env.vps
```

Authorized Testnet overlay:

```text
deploy/vps/.env.testnet-campaign
```

The production file always retains:

```env
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
```

The Testnet overlay contains only the expiring campaign authorization and isolated Testnet credentials. It is ignored by Git and must have mode `0600`.

## Production deployment

From the repository on the VPS:

```bash
cd /opt/sharipovai-repo/deploy/vps
cp .env.vps.example .env.vps
chmod 600 .env.vps
python3 validate_runtime_env.py --env-file .env.vps --mode production
```

Deploy the exact reviewed `main` through the protected updater:

```bash
sudo APP_DIR=/opt/sharipovai-repo \
  bash /opt/sharipovai-repo/deploy/vps/update_from_main.sh
```

Verify production-safe state:

```bash
sudo bash /opt/sharipovai-repo/deploy/vps/smoke_check.sh production
```

The smoke check validates rendered Compose flags, container health and canonical database health. A failed candidate is rolled back by the protected updater.

## Prepare the bounded Testnet window

Create the isolated overlay:

```bash
cd /opt/sharipovai-repo/deploy/vps
cp .env.testnet-campaign.example .env.testnet-campaign
chmod 600 .env.testnet-campaign
```

Set only:

```env
PHASE6_TESTNET_RELEASE_GATE=green
BYBIT_TESTNET_API_KEY=<isolated-testnet-key>
BYBIT_TESTNET_API_SECRET=<isolated-testnet-secret>
```

The Bybit key must be Testnet-only and must not have withdrawal or transfer permissions.

Validate the merged configuration without starting execution:

```bash
python3 validate_runtime_env.py \
  --env-file .env.vps \
  --env-file .env.testnet-campaign \
  --mode testnet-campaign
```

## Enter bounded Testnet runtime

This transition requires an exact operator phrase, creates a verified backup, renders the explicit override and rolls back to production-safe mode on any error:

```bash
sudo bash deploy/vps/testnet_campaign_deploy.sh \
  I_APPROVE_BOUNDED_TESTNET_RUNTIME_DEPLOYMENT
```

Expected terminal line:

```text
TESTNET_RUNTIME_READY ... mainnet=false max_notional_usdt=25
```

This only enables the already-audited bounded Testnet path. It does not start a campaign and cannot enable Mainnet.

## Run the first campaign and collect real evidence

First inspect the canonical plan:

```bash
docker exec sharipovai python scripts/testnet_campaignctl.py plan \
  --experiment-id '<promoted-experiment-id>' \
  --confirmation I_APPROVE_BOUNDED_TESTNET_SHADOW_CAMPAIGN
```

Proceed only with `can_start=true` and no blockers.

Run the finite campaign collector:

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

A stopped runner can resume the same non-terminal campaign:

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

The runner exits successfully only when all of these are proven:

- campaign status is `completed`;
- at least 20 matched Paper/Testnet fills;
- actual private execution fees are present;
- zero unmatched Paper or Testnet fills;
- zero orphan executions;
- zero duplicate identities;
- zero unresolved intents;
- final report is eligible for a separate manual decision.

Anything else exits with code `2` and `real_fill_evidence_confirmed=false`.

## Evidence bundle

Each campaign writes under the persistent data volume:

```text
/var/lib/sharipovai/evidence/testnet-campaigns/<campaign-id>/
├── campaign-start.json
├── campaign-latest.json
├── cycles.jsonl
├── final-promotion-report.json
├── operations-final.json
└── runner-result.json
```

The parent directory also retains `launch-plan.json`. The bundle supplements the canonical database; it does not replace it.

## Critical alerts

`CampaignCriticalAlertService` persists and deduplicates alerts for:

- more than one non-terminal campaign;
- kill switch engaged during an active campaign;
- non-restart-safe execution reconciliation;
- stale/unready private order and execution stream;
- blocked campaign;
- orphan, duplicate, unresolved, reconciliation or notional gate failure;
- orchestrator errors.

Alerts are always stored in `ProjectDatabase`. Optional external delivery is configured in `.env.vps`:

```env
CRITICAL_ALERT_MONITOR_ENABLED=1
CRITICAL_ALERT_MONITOR_SECONDS=15
CRITICAL_ALERT_REPEAT_SECONDS=900
ALERT_DELIVERY_ENABLED=1
ALERT_TELEGRAM_CHAT_ID=<chat-id>
ALERT_WEBHOOK_URL=https://<trusted-endpoint>
```

Telegram delivery additionally uses `BOT_TOKEN`. Non-HTTPS webhooks are rejected. Delivery failures do not erase alert evidence.

## Dashboard operations

Open:

```text
https://<DOMAIN>/#campaigns
```

The page now provides:

- live control-plane health and staleness;
- campaign selection and history;
- matched-fill progress and actual fee evidence;
- identity-integrity counters;
- open critical alerts and manual alert evaluation;
- complete release gates and blockers;
- schedule creation and scheduler tick;
- selected campaign cycle and final report actions;
- exact launch confirmation helper;
- responsive mobile/tablet layout and visibility-aware auto-refresh.

Every mutation still passes through authenticated admin APIs and canonical services.

## Restore production-safe mode

Immediately after completion, block, timeout or operator abort:

```bash
sudo bash deploy/vps/testnet_campaign_stop.sh \
  I_APPROVE_RESTORE_PRODUCTION_KILL_SWITCH
```

Expected terminal line:

```text
PRODUCTION_LOCKS_RESTORED kill_switch=1 testnet_execution=0 mainnet=false
```

Then remove or securely archive the Testnet overlay:

```bash
sudo shred -u deploy/vps/.env.testnet-campaign
```

Use a secure secret manager instead when available.

## Abort conditions

Restore production-safe mode immediately on:

- any orphan, duplicate, unresolved or conflicting identity;
- stale private stream;
- failed startup/execution reconciliation;
- notional outside 10–25 USDT;
- missing actual fee evidence;
- ambiguous exchange outcome;
- more than one active campaign;
- CI no longer green for the deployed commit;
- unexpected production Bybit URL or any Mainnet credential;
- critical alert that cannot be explained from canonical evidence.

Never fabricate a fill, patch evidence manually or blind-retry an ambiguous request.
