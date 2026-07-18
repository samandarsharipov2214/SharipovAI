# Phase 8 — Production Campaign Intelligence

Status: implementation package. A real campaign is complete only after authenticated private evidence proves every gate.

## Scope

Phase 8 adds four layers around the existing canonical Campaign Operations service:

1. one bounded Testnet execution window using the existing Phase 7 launcher and finite runner;
2. one-second sequence-aware Dashboard polling;
3. advanced operational alerts including drawdown;
4. immutable post-campaign analysis and a non-binding promotion recommendation.

No second exchange-write path is introduced.

## Campaign completion

Required evidence:

- 10–25 USDT accepted notional;
- 20+ matched Paper/Testnet fills;
- 20+ campaign-bound private execution IDs;
- actual private fees;
- zero unmatched Paper or Testnet fills;
- zero orphan, duplicate, conflicting or unresolved identities;
- fresh private order and execution streams;
- restart-safe startup and execution reconciliation;
- canonical final promotion report;
- immutable Phase 8 analysis.

Synthetic fixtures, screenshots, copied JSON and order acceptance are not completion evidence.

## Live view

The Phase 8 live view combines:

- Campaign Operations snapshot;
- Phase 7 private-fill monitor;
- fill progress and fees;
- execution-cost and canonical drawdown;
- P95 latency and slippage divergence;
- partial-fill rate;
- persistent critical alerts;
- immutable terminal analysis;
- promotion recommendation.

The browser polls once per second and sends the last observed sequence. The backend returns a versioned persistent snapshot. UI rendering is additive and does not replace launch or manual-decision controls.

## Advanced alerts

The combined live view exposes:

- kill switch engaged during an active campaign;
- startup or execution reconciliation failure;
- stale private stream;
- stale monitor heartbeat;
- multiple active campaigns;
- campaign blockers;
- orphan, duplicate or unresolved evidence;
- notional violation;
- drawdown breach;
- reject or hold recommendation;
- analysis failure.

Alerts are evidence and operator signals. They do not mutate execution flags.

## Post-campaign analysis

`Phase8PostCampaignAnalyzer` derives:

- actual private fill count and unique execution identities;
- executed notional;
- actual fee total and fee rate;
- maker/taker distribution;
- campaign duration and fill rate;
- P95 latency, slippage and fee divergence;
- partial-fill rate;
- execution-cost drawdown;
- canonical drawdown when campaign metrics provide it;
- immutable evidence SHA-256.

Possible recommendations:

- `PROMOTE_TO_EXTENDED_TESTNET`;
- `HOLD_AND_TUNE`;
- `REJECT_AND_INVESTIGATE`;
- `CONTINUE_BOUNDED_CAMPAIGN`.

A recommendation cannot promote a strategy, allocate capital, change runtime flags or enable Mainnet. A separate manual decision remains mandatory.

## Read-only API

```text
GET /api/campaigns/phase8/live
GET /api/campaigns/phase8/analysis/{campaign_id}
GET /api/campaigns/phase8/recommendation/{campaign_id}
```

The API requires administrator authentication and exposes no POST route.

## Production sequence

```text
complete green CI
-> merge Phase 7
-> deploy and verify production-safe mode
-> validate isolated Testnet authorization
-> enter bounded Testnet window
-> run existing finite campaign runner
-> capture 20+ actual private fills
-> generate canonical final report
-> create immutable Phase 8 analysis
-> restore production locks
-> review recommendation manually
```

## Truth rule

Until the private execution store contains 20+ campaign-bound execution IDs and the canonical final report exists, the truthful status is:

```text
Phase 8 implementation ready; real production campaign not yet completed.
```
