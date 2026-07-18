# SharipovAI Constitution

Version: `2026.07-phase11-deep-audit-v15`  
Status: **Binding development and runtime policy**

This document defines non-negotiable rules for research, execution, risk, campaigns,
scaling, evidence, CI, dashboards, security and deployment. A conflicting feature is
invalid even when it appears profitable or operationally convenient.

## 1. Capital protection and compile lock

1. Capital preservation has priority over activity, speed and profit.
2. Mainnet execution is compiled out while `MAINNET_EXECUTION_COMPILED=False`.
3. Environment variables, dashboard actions, Telegram, LLM output, stored state,
   experiments, reports, schedules, scaling authorities and manual decisions cannot
   override the compile lock.
4. Automated API keys must not have withdrawal or transfer permissions.
5. Future Mainnet operation requires a separate audited build, limited subaccount,
   measured Testnet evidence, legal review and an expiring owner approval.
6. Automatic martingale, averaging down, leverage increase and all-in allocation are forbidden.
7. Promotion, leadership, campaign and scaling records are evidence authority only.
   They are never direct exchange authority.

## 2. Promotion stages and promotion gate

```text
READ_ONLY -> PAPER -> TESTNET -> CONTROLLED_MAINNET -> SCALE
```

Skipping a stage is forbidden.

- `READ_ONLY`: public/private reads without exchange writes.
- `PAPER`: virtual capital and fills using verified market evidence.
- `TESTNET`: bounded writes through `ApprovedExecutionRequest`, durable idempotency,
  actual Bybit filters, authenticated private evidence and reconciliation.
- `CONTROLLED_MAINNET`: unavailable while `MAINNET_EXECUTION_COMPILED=False`.
- `SCALE`: never automatic and requires measured evidence plus owner approval.

Promotion is blocked by failed or skipped CI, missing out-of-sample evidence, stale
private streams, fill divergence, data-quality failure, orphan evidence, duplicate
identities, unresolved orders, reconciliation failure or breached loss/drawdown limits.
Failed automated gates cannot be overridden.

## 3. Canonical decision and execution path

```text
Market Intelligence
  -> Portfolio snapshot
  -> Risk Engine hard limits
  -> Correlation-aware capital allocation
  -> Decision Quality
  -> Security Guard
  -> TradingCandidate validation
  -> Paper execution
  -> Active campaign authorization where required
  -> Testnet shadow plan
  -> Actual Bybit fee/instrument validation
  -> ApprovedExecutionRequest
  -> Idempotency reservation
  -> Bybit Testnet executor
  -> Private order topic
  -> Private execution topic
  -> Runtime Fill Harvester
  -> Order/execution reconciliation
  -> Final promotion report
  -> Manual decision
```

No dashboard, Telegram handler, Learning Engine, agent, strategy, scheduler, CLI or LLM
may call an exchange order endpoint directly. The only exchange write entry is:

```python
BybitExecutionClient.execute(approved_request)
```

## 4. Idempotency and unknown outcomes

1. Every request has a deterministic `sai_...` `orderLinkId` derived from immutable intent.
2. Intent is reserved in `ProjectDatabase` before the network request.
3. The same intent cannot be submitted twice.
4. A timeout after reservation is an ambiguous financial outcome, not a retry signal.
5. Ambiguous requests remain unresolved until authenticated private evidence or explicit
   operator reconciliation resolves them.
6. Startup remains blocked for missing journal evidence, orphan orders/fills, identifier
   mismatch, quantity mismatch or unresolved intent.
7. Retry requires a new explicit attempt identity.

## 5. Private order and execution evidence

The read-only private WebSocket must subscribe to both `order` and `execution`.

Private order and execution evidence is canonical:

- `execId` is write-once;
- exact replay is deduplicated;
- conflicting reuse of `execId` blocks reconciliation;
- quantity, price, value, time, maker/taker state and actual fees are persisted;
- partial fills are aggregated by `orderLinkId`;
- cumulative order quantity must equal summed execution quantity;
- executions without private orders are orphan evidence;
- executed private orders without execution rows are missing evidence;
- stale streams and missing heartbeats block startup and execution.

A fee that cannot be normalized using verified evidence blocks approval.

## 6. Hard risk and capital limits

Hard limits override confidence, consensus, strategy output and expected profit.
Mandatory blocks include stale data, kill switch, invalid instrument, loss/drawdown,
exposure/correlation limits, liquidity floor, maximum positions, missing evidence,
non-finite values, expired requests, duplicates, unresolved identities and Mainnet.

Default research/Paper policy:

| Rule | Default |
| --- | ---: |
| Cash reserve | 20% |
| Maximum total exposure | 80% |
| Maximum one position | 20% |
| Maximum correlated group | 35% |
| Maximum risk per trade | 1% |
| Maximum daily loss | 2% |
| Leverage | 1× |

Soft risk may only reduce size: `LOW=1.0`, `MEDIUM=0.6`, `HIGH=0.25`, `CRITICAL=0.0`.

## 7. Correlation-aware sizing

1. Missing correlation evidence is not zero correlation; it blocks sizing.
2. Correlations must be finite and within `[-1, 1]`.
3. Duplicate open-position rows are aggregated by symbol.
4. Existing same-symbol exposure reduces remaining position capacity.
5. Existing correlated exposure reduces remaining cluster capacity.
6. The final notional is the smallest value allowed by risk budget, volatility,
   position capacity, cluster capacity, scaling authority and absolute Testnet ceiling.
7. Any invalid, missing or non-finite input returns zero authorized notional.

## 8. Paper realism and historical-data integrity

Only capital and fills are virtual. Quotes, timestamps, spread, maker/taker fees,
slippage, impact, funding, risk, drawdown and evidence are production-style.
Synthetic prices, fabricated trades and fake catch-up fills are forbidden.

Backtests:

1. process immutable events in `(timestamp, symbol)` order;
2. forbid lookahead, future leakage, duplicate bars and random time-series splits;
3. include spread, fees, slippage, participation impact and funding;
4. share models, costs and risk rules with Paper/Testnet where applicable;
5. record configuration, historical manifest identity and commit SHA;
6. require versioned, validated datasets and visible missing intervals;
7. compare candidates with buy-and-hold, trend, breakout and mean reversion;
8. require sequential walk-forward out-of-sample evidence;
9. remain evidence, never permission to trade.

## 9. Experiment registry and manual approval rules

Every candidate requires a persistent experiment record with immutable ID, source commit,
validated manifest SHA-256, strategy/backtest configuration, walk-forward results,
benchmarks, data validation, Paper summary, Paper/Testnet fill validation, automated
promotion report and explicit manual decision.

The experiment registry uses optimistic versions and append-only events. Automatic
experiments may fail closed but may never change stage, champion, execution flags or
deployment.

Manual approval rules:

1. every target requires a current automated report;
2. tokens are bound to experiment/stage or campaign/report/action;
3. actor and non-empty reason are mandatory;
4. failed automated gates cannot be overridden;
5. approval/rejection is immutable evidence only;
6. approval cannot change flags, credentials, capital, deployment or Mainnet state.

## 10. Initial Testnet shadow policy

Paper and Testnet share one source candidate but retain separate observations.

- Initial accepted Testnet notional is bounded to **10–25 USDT** per order.
- Dynamic Bybit filters, private streams and startup reconciliation are mandatory.
- Historical Paper trades cannot be replayed into a new campaign.
- Mainnet execution is compiled out.

A completed campaign requires:

| Gate | Requirement |
| --- | ---: |
| Matched Paper/Testnet fills | 20+ actual matched fills |
| Unmatched Paper fills | 0 |
| Unmatched Testnet fills | 0 |
| Orphan order/execution evidence | zero orphan |
| Duplicate/conflicting identities | 0 |
| Unresolved execution intents | 0 |
| Actual private execution fees | Present |
| Private stream | Fresh and authenticated |
| Reconciliation | Restart-safe |

A sample below 20 matched fills remains running, not successful.

## 11. Scheduled campaigns and single authorization

1. The scheduler may use only an experiment manually approved for `testnet`.
2. State is persisted in `ProjectDatabase`.
3. The worker is disabled by default.
4. At most one global non-terminal campaign authorization may exist.
5. A due schedule creates bounded authorization, not raw order authority.
6. Campaign authorization is bound to campaign ID, experiment ID and scope.
7. Trades created before activation cannot be attached to a campaign.
8. Failures are persisted and never retried as blind exchange submissions.
9. Scheduler actions cannot change runtime flags or Mainnet availability.

## 12. Controlled scaling authority

A Phase 10 scaling authority additionally requires:

1. an eligible Phase 9 plan with no failed or non-passing gates;
2. at least two distinct clean campaigns;
3. finite current and proposed notionals;
4. an increase no greater than `1.5x`;
5. an absolute Testnet ceiling no greater than `50 USDT`;
6. exact confirmation `I_APPROVE_CONTROLLED_TESTNET_NOTIONAL_SCALING`;
7. a canonical SHA-256 authority hash;
8. one persistent global optimistic lock;
9. an explicit scope and finite expiration time;
10. `testnet` environment, canonical path only, no kill-switch override and Mainnet false.

Only one valid scaling authority may exist globally. Expired, revoked, tampered,
non-finite or lock-mismatched authority fails closed. Scaling is never automatic.

## 13. Performance evidence and monthly reports

1. Phase 9 campaign reports create immutable Phase 10 performance snapshots.
2. Each snapshot has an evidence SHA-256 over its stable timestamp and metrics.
3. Exact replay is idempotent; conflicting identity reuse is forbidden.
4. Monthly reports verify every snapshot hash before aggregation.
5. Reports use evidence-derived IDs and retain previous monthly history.
6. Net PnL, fees, matched fills and maximum drawdown are mandatory.
7. Drawdown above policy creates a critical alert and failed service result.
8. A month with no matched fills remains visible and cannot be called successful.

## 14. First real Testnet campaign

A real bounded campaign requires complete current-head CI, isolated Testnet credentials,
private `order` and `execution` health, restart-safe reconciliation, approved experiment
evidence, zero active campaigns and an explicit finite operator window.

A campaign start row is not execution proof. Completion requires 20+ actual matched
private fills, actual fees and zero orphan, duplicate, unmatched or unresolved evidence.
Synthetic fixtures, screenshots or copied JSON cannot substitute for private evidence.

## 15. Operator control plane

`scripts/testnet_campaignctl.py` is the operator control plane over canonical services.

- `snapshot` and `plan` are read-only.
- `start`, `cycle`, `report` and `decision` require distinct confirmations.
- The operator CLI cannot set environment variables, install credentials, disable the
  kill switch, submit raw orders, deploy code or enable Mainnet.
- Manual report generation is idempotent for unchanged immutable evidence.
- Campaign decisions are bound to campaign ID, report ID and action.

## 16. Final report and decision flow

The final report combines experiment identity, campaign metrics, fill divergence,
private stream health, startup reconciliation, order/execution reconciliation, actual
fees and zero identity-failure gates. It stores evidence SHA-256 and returns only
`eligible_for_manual_decision` or `blocked`.

Automatic report generation never removes the separate manual decision. A blocked report
cannot be approved.

## 17. Dashboard and API security

1. Sensitive Phase 10/11 routes require an active administrator.
2. Authorization occurs in middleware before request body parsing.
3. API models reject extra fields, invalid symbols and non-finite floats.
4. Dashboard values use safe DOM APIs, not `innerHTML`, `insertAdjacentHTML` or `eval`.
5. Real-time requests require timeout, cancellation, visibility awareness and backoff.
6. Missing, stale or failed API data is displayed as unavailable or blocked, never invented.
7. Dark/light themes, mobile layout, keyboard focus and reduced motion are mandatory.
8. The dashboard cannot change the Mainnet compile lock.

## 18. Production audit and deployment

Production readiness requires:

- immutable approved commit SHA and clean worktree;
- dependency audit, compilation, full pytest and dedicated crash tests;
- compile/runtime Mainnet lock and engaged kill switch;
- auth enabled, database required and exchange sandbox mode;
- canonical SQLite/PostgreSQL database health;
- tracked secret-file hygiene;
- atomic post-deploy evidence with SHA-256;
- persistent monthly monitoring timer;
- rollback instructions and verified alerting.

The deterministic audit hash excludes timestamps and host metadata. Identical audited
state must produce identical SHA-256 evidence.

## 19. CI cleanroom and crash rules

Merge requires dependency installation, `pip check`, `pip-audit`, compilation, hard
Mainnet lock, execution/idempotency/reconciliation tests, private order/execution tests,
campaign operations tests, actual fee validation, research audits, complete pytest,
Phase 10/11 crash tests, retained artifacts and rollback instructions.

The CI cleanroom runs before application imports and:

1. verifies kill switch enabled and execution flags disabled;
2. rejects production exchange mode/base URL;
3. deletes only explicit SQLite/WAL/journal/runtime-state paths;
4. permits deletion only inside the GitHub workspace or `/tmp`;
5. refuses broad filesystem discovery and unsafe roots;
6. retains JSON reset/audit evidence;
7. fails collection on any violation.

Every failure is classified as `regression`, `stale_test` or
`environment_contamination`. Classification cannot turn failed, missing, queued or
skipped CI green.

Mandatory crash scenarios include restart, network timeout, database failure, malformed
payload, duplicate order/authority identity, non-finite data, stale streams, expired
permissions, corrupted evidence and concurrent activation.

## 20. Database, evidence and secrets

`ProjectDatabase` is the canonical source of truth for experiments, results, schedules,
campaigns, reports, decisions, leadership, intents, private order/execution state,
reconciliation, validation, scaling, performance, audit and project memory.

Secrets, keys, seed phrases, credentials and tokens are forbidden in Git, logs, metrics,
experiments, reports, test artifacts and documentation examples.

## 21. Profit and user claims

SharipovAI reports measured results after all modeled and actual available costs. It must
not promise guaranteed income, fabricate performance or scale capital based only on a
backtest, confidence score or narrative.

## Change history

| Version | Date | Summary |
| --- | --- | --- |
| `2026.07-phase11-deep-audit-v15` | 2026-07-19 | Controlled scaling integrity, correlation fail-closed sizing, immutable performance history, deterministic production audit, crash CI, secure dashboard and deployment hardening. |
| `2026.07-ci-cleanroom-testnet-operations-v9` | 2026-07-16 | Repository-wide fail-closed pytest cleanroom, bounded campaign operator CLI and first-real-Testnet runbook. |
| `2026.07-legacy-campaign-operations-v8` | 2026-07-15 | Legacy taxonomy, import-order-safe auth and Campaign Operations contracts. |
| `2026.07-scheduled-execution-evidence-v7` | 2026-07-14 | Scheduled orchestrator, private evidence and bounded campaigns. |
| `2026.07-research-promotion-v4` | 2026-07-14 | Versioned data, funding/impact modeling, walk-forward evaluation and benchmarks. |
| `2026.07-execution-research-v3` | 2026-07-14 | Durable idempotency, reconciliation, hard risk limits and event-driven backtesting. |
| `2026.07-safety-foundation-v2` | 2026-07-14 | Mainnet compile lock, canonical execution request and truthful CI. |
