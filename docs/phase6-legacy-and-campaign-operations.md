# Phase 6 — Legacy Contract Stabilization and Campaign Operations

## Scope

Phase 6 stabilizes legacy contracts without weakening current safety architecture and
adds an operational control plane for the first bounded Testnet shadow campaign.
It does not enable Mainnet, modify runtime flags, approve an experiment or invent
fills.

## Baseline classification

The current full-suite evidence contained 100 failures. Running
`scripts/legacy_contract_classifier.py` against that JUnit artifact classified the
baseline as:

| Class | Count | Required action |
| --- | ---: | --- |
| regression | 61 | Fix production/runtime behavior or prove the contract correct |
| stale_test | 30 | Rewrite exact-version, removed API or obsolete-copy assertions semantically |
| environment_contamination | 9 | Isolate runner package layout, state, credentials or network dependency |

Unknown failures always default to `regression`. Classification never changes the
truthful CI outcome. A failed test remains failed until the underlying problem or
stale test is corrected.

```bash
python scripts/legacy_contract_classifier.py \
  --junit artifacts/pytest.xml \
  --json artifacts/legacy-contract-classification.json \
  --markdown artifacts/legacy-contract-classification.md
```

## Compatibility stabilization

Phase 6 compatibility layers are narrow adapters, not rollback paths:

- configured administrator credentials take precedence over pending persisted users;
- session decoding and global middleware use one canonical resolver;
- legacy app-local session hooks remain available to isolated tests;
- News Intelligence restores historical callable aliases but routes every operation
  to the canonical `ProjectDatabase`-backed network;
- Telegram native-command restoration is a recovery helper only; normal webhook
  setup preserves the canonical SharipovAI Mini App menu;
- execution-stage tests use `ApprovedExecutionRequest` only;
- Testnet bridge tests accept persisted ignored records and reject untrusted Paper
  rows as promotion evidence.

## Campaign Operations UI

The `Кампании` page and `/api/campaigns/operations` expose:

- scheduled campaign rows and next-run time;
- single active campaign authorization;
- matched-fill progress against the 20-fill minimum;
- orphan, duplicate and unresolved counters;
- actual private execution fee total;
- final report readiness and immutable report ID;
- exact release blockers for the first bounded Testnet campaign.

The UI never writes environment variables and has no raw-order primitive.

## First bounded Testnet campaign

Contract:

| Gate | Required |
| --- | ---: |
| Environment | Bybit Testnet / sandbox |
| Category | Spot |
| Per-order notional | 10–25 USDT |
| Matched Paper/Testnet fills | 20+ |
| Orphan executions | 0 |
| Duplicate order identities | 0 |
| Unresolved execution intents | 0 |
| Private order + execution stream | Ready |
| Actual private execution fees | Required |
| Startup reconciliation | Restart-safe |
| Experiment | Automated gate passed + explicit manual Testnet approval |
| Mainnet | Compiled out |

Launch also requires:

```text
PHASE6_TESTNET_RELEASE_GATE=green
I_APPROVE_BOUNDED_TESTNET_SHADOW_CAMPAIGN
```

The release-gate environment value is an operations acknowledgement after green CI;
application code does not set it. The confirmation phrase is required on the admin
API and Campaign Operations UI.

```http
GET  /api/campaigns/first-testnet/plan?experiment_id=<promoted-id>
POST /api/campaigns/first-testnet/start
```

Example body:

```json
{
  "experiment_id": "experiment_...",
  "scope": "BTCUSDT",
  "confirmation": "I_APPROVE_BOUNDED_TESTNET_SHADOW_CAMPAIGN"
}
```

A successful start creates only the existing campaign authorization and immediately
runs the existing campaign state machine. It does not change flags. Completion
causes the existing `FinalPromotionReportEngine` to generate the immutable final
report automatically. Promotion remains a separate manual decision.

## Definition of done

Phase 6 is not complete merely because the UI exists. It is complete only when:

1. Phase 6 targeted regressions are green.
2. The full suite has no unresolved regressions or environment contamination.
3. Stale tests have been rewritten to semantic current contracts.
4. Testnet credentials and private streams are healthy.
5. One bounded campaign records at least 20 actual matched fills.
6. Orphan, duplicate, unmatched and unresolved counts are zero.
7. Actual execution fees are present.
8. The immutable final report is generated.
9. Mainnet remains compiled out.
