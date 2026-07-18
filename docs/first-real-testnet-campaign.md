# First Real Testnet Shadow Campaign Runbook

Status: **not completed until authenticated private execution evidence is captured.**

This runbook executes one bounded Bybit Testnet campaign. It cannot enable Mainnet, install credentials from application code, bypass reconciliation or treat synthetic fixtures as evidence.

**Synthetic fills are not evidence. Completion requires actual private execution IDs and fees captured from authenticated private order and execution streams.**

## Completion contract

| Evidence | Requirement |
| --- | ---: |
| Accepted Testnet notional | 10–25 USDT per order |
| Matched Paper/Testnet fills | 20+ |
| Unmatched Paper fills | 0 |
| Unmatched Testnet fills | 0 |
| Orphan executions | 0 |
| Duplicate/conflicting identities | 0 |
| Unresolved intents | 0 |
| Actual private execution fees | Present |
| Private `order` + `execution` stream | Authenticated and fresh |
| Startup/execution reconciliation | Restart-safe |
| Final report | Eligible for manual decision |
| Mainnet | Compiled out and disabled |

A campaign row, REST acceptance, screenshot, Paper-only fill or copied JSON is not proof.

## 1. Verify reviewed deployment

The deployed commit must have complete green required CI. A queued, skipped, partial or failed workflow is not approval.

```bash
cd /opt/sharipovai-repo
sudo APP_DIR=/opt/sharipovai-repo bash deploy/vps/update_from_main.sh
sudo bash deploy/vps/smoke_check.sh production
```

## 2. Prepare isolated authorization

```bash
cd /opt/sharipovai-repo/deploy/vps
cp .env.testnet-campaign.example .env.testnet-campaign
chmod 600 .env.testnet-campaign
```

Populate only the current release gate and isolated Bybit Testnet key/secret. The key must not allow withdrawal or transfer.

```bash
python3 validate_runtime_env.py \
  --env-file .env.vps \
  --env-file .env.testnet-campaign \
  --mode testnet-campaign
```

## 3. Enter bounded Testnet mode

```bash
cd /opt/sharipovai-repo
sudo bash deploy/vps/testnet_campaign_deploy.sh \
  I_APPROVE_BOUNDED_TESTNET_RUNTIME_DEPLOYMENT
```

The script runs target preflight, creates a verified backup, validates rendered Compose, starts the explicit Testnet override, checks health/database state and restores production-safe mode on failure.

## 4. Inspect readiness

```bash
docker exec sharipovai python scripts/testnet_campaignctl.py snapshot
```

```bash
docker exec sharipovai python scripts/testnet_campaignctl.py plan \
  --experiment-id '<promoted-experiment-id>' \
  --confirmation I_APPROVE_BOUNDED_TESTNET_SHADOW_CAMPAIGN
```

Proceed only when `status=ready`, `can_start=true` and `blockers=[]`.

## 5. Run finite evidence collection

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

The process is finite. It returns exit code `0` only with `real_fill_evidence_confirmed=true`; otherwise it returns `2` and preserves the partial evidence bundle.

## 6. Observe campaign operations

Open the authenticated **Кампании** page or inspect:

```text
GET /api/campaigns/operations
GET /api/campaigns/phase7/monitor?refresh=true
GET /api/campaigns/phase7/fills
GET /api/campaigns/phase7/alerts
```

Watch:

- matched fills and remaining target;
- actual private execution count and fee total;
- unmatched Paper/Testnet counts;
- orphan, duplicate and unresolved counters;
- private stream freshness;
- startup/execution reconciliation;
- persistent critical alerts;
- final report status and export path.

## 7. Resume after operator-process interruption

Do not start a second campaign. Resume the same campaign ID:

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

Resume is blocked if any readiness failure exists beyond the expected `no_active_campaign` gate caused by that same running campaign.

## 8. Review immutable report

The completed campaign creates a canonical report automatically. Idempotent manual retrieval:

```bash
docker exec sharipovai python scripts/testnet_campaignctl.py report \
  --campaign-id '<campaign-id>' \
  --actor '<authenticated-operator>' \
  --confirmation I_APPROVE_IMMUTABLE_CAMPAIGN_REPORT
```

The report must be eligible for manual decision, contain no failed gates, retain its evidence SHA-256 and keep `mainnet_enabled=false`.

## 9. Separate manual decision

Only after reviewing the final report:

```bash
docker exec sharipovai python scripts/testnet_campaignctl.py decision \
  --campaign-id '<campaign-id>' \
  --action approve \
  --reason '20+ authenticated matched fills, actual fees, zero identity failures' \
  --approval-token 'CAMPAIGN_DECISION:<campaign-id>:<report-id>:APPROVE' \
  --actor '<authenticated-operator>' \
  --confirmation I_APPROVE_MANUAL_CAMPAIGN_DECISION
```

Approval is evidence only. It does not deploy code, change flags, allocate capital or enable Mainnet.

## 10. Close the execution window

Always restore locks after completion, failure, timeout or abort:

```bash
sudo bash deploy/vps/testnet_campaign_stop.sh \
  I_APPROVE_RESTORE_PRODUCTION_KILL_SWITCH
```

Verify:

```bash
sudo bash deploy/vps/smoke_check.sh production
```

## Immediate abort conditions

- stale/disconnected private stream or monitor heartbeat;
- orphan execution or missing private order;
- duplicate/conflicting `execId` or order identity;
- unresolved submission outcome;
- quantity/order-link mismatch;
- notional outside 10–25 USDT;
- missing actual fee evidence;
- unexpected environment or production exchange URL;
- more than one non-terminal campaign;
- required CI no longer green;
- persistent unexplained critical alert.

Persist evidence, restore production locks and investigate. Never blind-retry an ambiguous order.
