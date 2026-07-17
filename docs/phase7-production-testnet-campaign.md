# Phase 7 — Production Stabilization and First Bounded Testnet Campaign

Status: implementation complete; real campaign evidence remains fail-closed until the canonical production gates are green and 20+ authenticated private fills exist.

## Delivered

Phase 7 adds an operational layer around the already existing canonical campaign and execution services. It does not introduce a second order path.

- VPS preflight before backup or code replacement.
- SQLite header and `PRAGMA quick_check` validation.
- Minimum free-disk guard and secret-file permission check.
- Docker init process, graceful shutdown, faster health convergence and bounded log rotation.
- Persistent Phase 7 campaign monitor.
- Three-second Dashboard polling for progress, heartbeat, alerts, actual private fills and actual fees.
- Atomic JSON export after the canonical immutable final report exists.
- Recovery of monitor state from the canonical campaign database.

## Authority boundary

The only campaign launch path remains `CampaignOperationsService.start_first_testnet_campaign` through the existing admin API or `scripts/testnet_campaignctl.py`.

The Phase 7 monitor:

- cannot write credentials;
- cannot alter execution flags;
- cannot disable the kill switch;
- cannot submit a raw order;
- cannot enable Mainnet;
- cannot fabricate a fill or fee;
- cannot promote a campaign automatically.

## Production readiness sequence

Run read-only readiness first:

```bash
cd /opt/sharipovai-repo
python scripts/testnet_campaignctl.py plan \
  --experiment-id EXPERIMENT_ID \
  --confirmation I_APPROVE_BOUNDED_TESTNET_SHADOW_CAMPAIGN
```

The command must return `can_start=true`. Mandatory evidence includes:

1. green current-head release gate;
2. sandbox exchange mode;
3. isolated Testnet credentials;
4. Testnet execution explicitly enabled for the campaign window;
5. execution kill switch explicitly released for the bounded window;
6. Mainnet compiled out and hard-blocked;
7. private order and execution topics authenticated and fresh;
8. restart-safe order/execution reconciliation;
9. runtime fill harvester and campaign orchestrator enabled;
10. one manually promoted Testnet experiment;
11. zero active campaigns.

## Launch

After all gates are green:

```bash
python scripts/testnet_campaignctl.py start \
  --actor OWNER \
  --experiment-id EXPERIMENT_ID \
  --scope BTCUSDT \
  --confirmation I_APPROVE_BOUNDED_TESTNET_SHADOW_CAMPAIGN
```

This creates one global bounded campaign authorization. It does not bypass candidate validation, risk limits, idempotency, private-stream readiness or reconciliation.

## Monitoring

Use the Dashboard **Кампании** page or the admin API:

```text
GET /api/campaigns/phase7/monitor?refresh=true
GET /api/campaigns/phase7/fills
GET /api/campaigns/phase7/report
```

The monitor reports:

- canonical campaign identity and status;
- matched fills versus the target;
- actual authenticated private executions only;
- actual execution fees;
- private-stream state;
- heartbeat age and stale state;
- orphan, duplicate, unresolved and unmatched alerts;
- immutable final report identity and export path.

## Completion definition

A start response, accepted order response, screenshot or Dashboard progress bar is not campaign completion.

Completion requires all of the following at the same evidence revision:

- at least 20 matched Paper/Testnet fills;
- each accepted order within 10–25 USDT notional;
- zero unmatched Paper fills;
- zero unmatched Testnet fills;
- zero orphan executions;
- zero duplicate order identities;
- zero conflicting execution identities;
- zero unresolved intents/orders;
- actual private execution fees;
- fresh private order and execution streams;
- restart-safe startup and execution reconciliation;
- canonical final promotion report generated;
- separate manual promotion decision still pending or explicitly recorded.

## Final report

When the canonical campaign reaches `completed`, the existing report engine creates the immutable promotion report. The Phase 7 monitor then exports a companion JSON file containing:

- canonical campaign state;
- actual private fill projection;
- canonical final promotion report;
- export timestamp;
- explicit `mainnet_enabled=false` evidence.

Default location:

```text
/var/lib/sharipovai/campaign_reports/<campaign_id>.json
```

## Deployment

`deploy/vps/update_from_main.sh` now runs the target commit's `phase7_preflight.sh` before the verified backup and before changing the production checkout.

Deployment order:

```text
fetch immutable target
  -> target preflight
  -> verified backup
  -> checkout exact target
  -> render and validate Compose
  -> build candidate
  -> replace services
  -> local health
  -> container health
  -> rollback on any failure
```

The preflight is evidence, not a substitute for CI. A failed, queued or skipped required workflow still blocks merge and deployment.

## Truth rule

Until the private execution store contains 20+ campaign-bound fills and the canonical final report exists, the only truthful status is:

```text
Campaign implementation ready; real bounded campaign not yet completed.
```
