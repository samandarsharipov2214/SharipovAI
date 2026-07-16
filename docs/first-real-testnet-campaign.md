# First Real Testnet Shadow Campaign Runbook

Status: **not authorized until complete CI and deployed private readiness are green**.

This runbook launches one bounded Bybit Testnet shadow campaign with 10–25 USDT
per accepted Testnet order and at least 20 matched Paper/Testnet fills. It does
not enable Mainnet and it does not install credentials or change runtime flags.

## 1. Non-negotiable prerequisites

All of the following must be true on the deployed Testnet runtime:

- current PR head has complete green `Tests`, `Project Guardrails` and dashboard checks;
- `MAINNET_EXECUTION_COMPILED=False`;
- `EXCHANGE_MODE=sandbox`;
- `EXCHANGE_BASE_URL=https://api-testnet.bybit.com`;
- isolated Bybit Testnet credentials are present outside Git and logs;
- credential permissions exclude withdrawal and transfer;
- `order` and `execution` private topics are authenticated, subscribed and fresh;
- startup reconciliation reports `restart_safe=true`;
- execution reconciliation has zero orphan, duplicate and unresolved identities;
- the candidate experiment is promoted and manually approved for `testnet`;
- no non-terminal campaign exists;
- kill switch and execution flags are changed only by the operator deployment procedure;
- `PHASE6_TESTNET_RELEASE_GATE=green` is set externally after CI review.

A queued, skipped or partial CI run is not approval. Synthetic fills are not evidence.

## 2. CI cleanroom verification

Each pytest process on GitHub Actions now executes the repository-wide
`conftest.py` cleanroom before application imports. It:

1. audits that execution remains disabled and the kill switch remains enabled;
2. rejects the production Bybit base URL;
3. removes only explicitly configured SQLite, WAL, journal and runtime-state paths;
4. refuses paths outside the GitHub workspace or `/tmp`;
5. writes `artifacts/runtime-state-<pid>.json`.

Manual audit without deletion:

```bash
python scripts/ci_runtime_state.py
```

Authorized CI reset:

```bash
GITHUB_ACTIONS=true python scripts/ci_runtime_state.py \
  --apply \
  --report artifacts/runtime-reset.json
```

Never run `--apply` with production paths.

## 3. Read-only deployed snapshot

```bash
python scripts/testnet_campaignctl.py snapshot
```

Expected invariants:

- `active_campaign_count` is `0` before launch;
- `single_global_campaign_authorization` is `true`;
- `mainnet_enabled` is `false`;
- `runtime_flags_changed` is `false`.

## 4. Evaluate the exact launch plan

```bash
python scripts/testnet_campaignctl.py plan \
  --experiment-id '<promoted-experiment-id>' \
  --confirmation I_APPROVE_BOUNDED_TESTNET_SHADOW_CAMPAIGN
```

Proceed only when:

```json
{
  "status": "ready",
  "can_start": true,
  "blockers": []
}
```

The command exits with status `2` while any gate is blocked.

## 5. Start one bounded campaign

```bash
python scripts/testnet_campaignctl.py start \
  --experiment-id '<promoted-experiment-id>' \
  --scope BTCUSDT \
  --actor '<authenticated-operator>' \
  --confirmation I_APPROVE_BOUNDED_TESTNET_SHADOW_CAMPAIGN
```

Immediately record the returned `campaign_id`. The start record is not proof of
execution and is not a promotion decision.

## 6. Run and observe cycles

The scheduled orchestrator may advance the campaign when enabled. A manual cycle
uses the same canonical state machine:

```bash
python scripts/testnet_campaignctl.py cycle \
  --campaign-id '<campaign-id>' \
  --actor '<authenticated-operator>' \
  --confirmation I_APPROVE_BOUNDED_TESTNET_CAMPAIGN_CYCLE
```

After each cycle, inspect Campaign Operations:

```bash
python scripts/testnet_campaignctl.py snapshot
```

Required completion evidence:

| Evidence | Requirement |
| --- | ---: |
| Accepted Testnet notional | 10–25 USDT per order |
| Matched private fills | 20+ |
| Unmatched Paper fills | 0 |
| Unmatched Testnet fills | 0 |
| Orphan executions | 0 |
| Duplicate order identities | 0 |
| Conflicting execution identities | 0 |
| Unresolved intents | 0 |
| Actual private execution fees | Present |
| Private `order` + `execution` health | Fresh |
| Startup/execution reconciliation | Restart-safe |

Any orphan, duplicate, unresolved identity or out-of-range notional hard-blocks
the campaign. Do not repair evidence manually and do not fabricate catch-up fills.

## 7. Divergence evidence

The `RuntimeFillHarvester` joins the campaign-bound Paper trade, bridge record,
`orderLinkId`, private order lifecycle and private execution rows. The immutable
validation report must contain actual private execution IDs and fees.

Review at minimum:

- first-fill latency;
- signed slippage;
- requested versus filled quantity;
- fill ratio and partial-fill rate;
- actual fee amount, currency and divergence;
- unmatched Paper/Testnet rows;
- report evidence SHA-256.

## 8. Final report

A completed campaign generates the final promotion report automatically. The
manual command is idempotent for the same immutable evidence:

```bash
python scripts/testnet_campaignctl.py report \
  --campaign-id '<campaign-id>' \
  --actor '<authenticated-operator>' \
  --confirmation I_APPROVE_IMMUTABLE_CAMPAIGN_REPORT
```

The report must be `eligible_for_manual_decision`, have no failed campaign gates
and retain `mainnet_enabled=false`.

## 9. Manual promotion decision

Read the campaign decision snapshot through the dashboard/API and copy the exact
action-bound approval or rejection token. Approval cannot override a blocked report.

```bash
python scripts/testnet_campaignctl.py decision \
  --campaign-id '<campaign-id>' \
  --action approve \
  --reason '20+ actual matched fills; zero identity failures; divergence within policy' \
  --approval-token 'CAMPAIGN_DECISION:<campaign-id>:<report-id>:APPROVE' \
  --actor '<authenticated-operator>' \
  --confirmation I_APPROVE_MANUAL_CAMPAIGN_DECISION
```

A rejection uses the `REJECT` token. Decisions are immutable evidence only. They
do not deploy code, change flags, allocate capital or enable Mainnet.

## 10. Abort conditions

Stop advancing the campaign and restore the kill switch immediately when any of
the following appears:

- stale or disconnected private stream;
- orphan execution or missing private order;
- duplicate/conflicting execution identity;
- unresolved submission outcome;
- quantity or order-link mismatch;
- notional outside 10–25 USDT;
- missing actual fee evidence;
- unexpected environment or production URL;
- more than one non-terminal campaign;
- CI status no longer green for the deployed head.

Persist the evidence and investigate. Never blind-retry an ambiguous order.

## 11. What is not yet evidence

The following do not prove that the real campaign ran:

- a campaign row with status `scheduled` or `running`;
- REST order acceptance without private execution evidence;
- Paper fills without matching Testnet executions;
- synthetic fixtures, screenshots or copied JSON;
- a final report built from fewer than 20 actual matched fills;
- a manual approval record without green automated gates.
