# SharipovAI Constitution

Version: `2026.07-ci-cleanroom-testnet-operations-v9`  
Status: **Binding development and runtime policy**

This document defines non-negotiable rules for code, AI organs, configuration,
research, CI, dashboards, campaigns, promotion and deployment. A conflicting
feature is invalid even when it appears profitable or operationally convenient.

## 1. Capital protection

1. Capital preservation has priority over activity, speed and profit.
2. Mainnet execution is compiled out while `MAINNET_EXECUTION_COMPILED=False`.
3. Environment variables, dashboard actions, Telegram, LLM output, stored state,
   experiments, schedules, reports and manual decisions cannot override the compile lock.
4. Automated API keys must not have withdrawal or transfer permissions.
5. Future Mainnet operation requires a separate audited build, a limited subaccount,
   measured Testnet evidence, legal review and an expiring owner approval.
6. Automatic martingale, averaging down, leverage increase and all-in allocation are forbidden.
7. Promotion, leadership and campaign records are evidence authority only. They are never
   direct execution authority.

## 2. Promotion stages

```text
READ_ONLY -> PAPER -> TESTNET -> CONTROLLED_MAINNET -> SCALE
```

Skipping a stage is forbidden.

- `READ_ONLY`: public/private reads without exchange writes.
- `PAPER`: virtual capital and fills using verified market evidence.
- `TESTNET`: bounded writes through `ApprovedExecutionRequest`, durable idempotency,
  actual Bybit filters, authenticated private evidence and reconciliation.
- `CONTROLLED_MAINNET`: unavailable while `MAINNET_EXECUTION_COMPILED=False`.
- `SCALE`: never automatic and requires measured live evidence plus owner approval.

Promotion is blocked by failed or skipped CI, unresolved identities, stale private
streams, orphan evidence, duplicate execution identities, reconciliation errors,
insufficient out-of-sample evidence, fill divergence, data-quality failure or a
breached drawdown/loss limit.

## 3. Canonical decision and execution path

```text
Market Intelligence
  -> Portfolio snapshot
  -> Risk Engine hard limits
  -> Risk-based capital allocation
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

No dashboard, Telegram handler, Learning Engine, agent, strategy, scheduler, CLI or
LLM may call an exchange order endpoint directly. The only exchange write entry is:

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

The read-only private WebSocket must subscribe to both:

```text
order
execution
```

Mandatory readiness evidence:

- isolated Testnet credentials configured;
- worker running, connected and authenticated;
- both topics subscribed;
- fresh persisted heartbeat;
- correct Testnet environment;
- zero unresolved order/execution reconciliation errors.

Private execution evidence is canonical:

- `execId` is write-once;
- exact replay is deduplicated;
- conflicting reuse of `execId` blocks reconciliation;
- quantity, price, value, time, maker/taker state, fee rate, fee amount and fee currency
  are persisted;
- partial fills are aggregated by `orderLinkId`;
- order cumulative quantity must equal summed execution quantity;
- executions without private orders are orphan evidence;
- executed private orders without execution rows are missing evidence.

A fee that cannot be normalized using verified conversion evidence blocks approval.

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
| Maximum one symbol | 20% |
| Maximum correlated group | 35% |
| Maximum risk per trade | 1% |
| Maximum daily loss | 2% |
| Leverage | 1× |

Soft risk may only reduce size: `LOW=1.0`, `MEDIUM=0.6`, `HIGH=0.25`, `CRITICAL=0.0`.

## 7. Paper realism and historical-data integrity

Only capital and fills are virtual. Quotes, timestamps, spread, maker/taker fees,
slippage, impact, funding, risk, drawdown and evidence are production-style.
Synthetic prices, fabricated trades and fake catch-up fills are forbidden.

Backtests:

1. process immutable events in `(timestamp, symbol)` order;
2. forbid lookahead, future leakage, duplicate bars and random time-series splits;
3. include spread, fees, slippage, participation impact and funding;
4. share models, costs and risk rules with Paper/Testnet where applicable;
5. record config, manifest identity and commit SHA;
6. require versioned, validated datasets;
7. keep missing intervals visible;
8. compare candidates with buy-and-hold, trend, breakout and mean reversion;
9. require sequential walk-forward out-of-sample evidence;
10. remain evidence, never permission to trade.

## 8. Experiment registry and promotion

Every candidate requires a persistent experiment record with immutable ID, source commit,
validated manifest identity/SHA-256, strategy/backtest config, walk-forward results,
benchmarks, data validation, Paper summary, Paper/Testnet fill validation, automated
promotion report and explicit manual decision.

```text
created -> running -> completed -> promotion_pending -> promoted/rejected
```

The registry uses optimistic versions and append-only events. Automatic experiments may
fail closed but may never change stage, champion, execution flags or deployment.

Manual approval rules:

1. every target requires a current automated report;
2. tokens are bound to experiment/stage or campaign/report/action;
3. actor and non-empty reason are mandatory;
4. failed automated gates cannot be overridden;
5. approval/rejection is immutable evidence only;
6. approval cannot change flags, credentials, capital, deployment or Mainnet state.

## 9. Testnet shadow policy

Paper and Testnet share one source candidate but retain separate observations.

- Testnet notional is bounded to **10–25 USDT** per accepted order.
- Dynamic Bybit filters, private streams and startup reconciliation are mandatory.
- Historical Paper trades cannot be replayed into a new campaign.
- Mainnet remains compiled out.

A completed Testnet Shadow Campaign requires:

| Gate | Requirement |
| --- | ---: |
| Matched Paper/Testnet fills | 20+ |
| Unmatched Paper fills | 0 |
| Unmatched Testnet fills | 0 |
| Orphan orders/executions | 0 |
| Duplicate order identities | 0 |
| Conflicting execution identities | 0 |
| Unresolved execution intents | 0 |
| Actual private execution fees | Present |
| Private stream | Fresh |
| Startup and execution reconciliation | Restart-safe |

Any orphan, duplicate, unresolved identity or out-of-range notional hard-blocks the
campaign. A sample below 20 matched fills remains running, not successful.

## 10. Scheduled campaigns and single authorization

1. The scheduler may use only an experiment already manually approved for `testnet`.
2. State is persisted in `ProjectDatabase`.
3. Minimum schedule interval is one minute.
4. The worker is disabled by default.
5. At most one global non-terminal campaign authorization may exist.
6. A due schedule creates bounded authorization, not raw order authority.
7. Campaign authorization is bound to campaign ID, experiment ID and scope.
8. Trades created before activation cannot be attached to the campaign.
9. Failures are persisted and never retried as blind exchange submissions.
10. Scheduler actions cannot change runtime flags or Mainnet availability.

## 11. First real Testnet campaign

The first real bounded campaign additionally requires:

```text
PHASE6_TESTNET_RELEASE_GATE=green
I_APPROVE_BOUNDED_TESTNET_SHADOW_CAMPAIGN
```

Application code may verify but may not set the release gate. The campaign may start only
when complete current-head CI, isolated credentials, private `order` + `execution` health,
restart-safe reconciliation, approved experiment evidence and zero active campaigns are
all proven.

A campaign start row is not proof of execution. Completion requires 20+ actual matched
private fills, actual fees and zero orphan, duplicate, unmatched or unresolved evidence.
Synthetic fixtures, screenshots or copied JSON cannot substitute for private evidence.

## 12. Operator control plane

`scripts/testnet_campaignctl.py` is a thin adapter over canonical services.

- `snapshot` and `plan` are read-only.
- `start`, `cycle`, `report` and `decision` require distinct exact confirmations.
- The CLI cannot set environment variables, install credentials, disable the kill switch,
  submit raw orders, deploy code or enable Mainnet.
- Manual report generation is idempotent for unchanged immutable evidence.
- Campaign decisions are bound to campaign ID, report ID and action.

## 13. Final report and decision flow

The Final Promotion Report combines experiment identity, campaign metrics, divergence,
private stream health, startup reconciliation, order/execution reconciliation, actual fees
and zero identity-failure gates. It stores an evidence SHA-256 and returns only
`eligible_for_manual_decision` or `blocked`.

Automatic report generation never removes the separate manual decision. A blocked report
cannot be approved.

## 14. Canonical architecture

SharipovAI has nine top-level AI organs:

1. General Controller
2. Market Intelligence
3. News Intelligence
4. Risk Engine
5. Portfolio Engine
6. Virtual Execution
7. Decision Quality
8. Learning Engine
9. Security Guard

Storage, transport, scheduler, registries, validation, observability, backtesting and
campaign orchestration are infrastructure, not additional AI organs.

## 15. Learning and legacy compatibility

Learning may create lessons, proposals and challengers. It may not deploy rules, enable
exchange writes, increase capital/leverage, remove Risk/Security vetoes, retry unresolved
orders or appoint a champion without approved evidence.

Compatibility adapters may preserve callable names or test hooks only when routing to the
current canonical implementation. They may not restore raw-order entry points, Mainnet
unlock behavior, synthetic sources or obsolete renderer ownership. Configured administrator
authentication must be independent of package import order.

## 16. CI cleanroom and merge rules

Merge requires dependency installation, `pip check`, `pip-audit`, compilation, critical
imports, hard Mainnet lock, execution/idempotency/reconciliation tests, private order and
execution tests, campaign policy/operations tests, actual fee validation, experiment/risk
research tests, foundation audits, critical coverage, complete pytest, retained artifacts
and rollback instructions.

A static score, partial suite, queued check or AI statement cannot override failed or
skipped CI. Testnet and Mainnet remain disabled in CI.

Every GitHub Actions pytest process must execute the repository cleanroom before application
imports. The cleanroom must:

1. verify kill switch enabled and execution flags disabled;
2. reject production exchange mode/base URL and a green Testnet release gate;
3. delete only explicitly configured SQLite/WAL/journal/runtime-state paths;
4. allow deletion only inside the GitHub workspace or `/tmp`;
5. refuse broad filesystem discovery and unsafe roots;
6. retain a JSON reset/audit artifact;
7. fail collection on any violation.

Every full-suite failure is assigned exactly one diagnostic class:

- `regression`;
- `stale_test`;
- `environment_contamination`.

Unknown failures are regressions. Classification is evidence only and cannot turn a failed,
missing, queued or skipped workflow green.

## 17. Database, evidence and secrets

`ProjectDatabase` is the canonical source of truth for experiments, results, schedules,
campaigns, reports, decisions, leadership, intents, private order/execution state,
reconciliation, validation, audit, learning and project memory.

Secrets, keys, seed phrases, credentials and tokens are forbidden in Git, logs, metrics,
experiments, reports, test artifacts and documentation examples.

## 18. Profit and user claims

SharipovAI reports measured results after all modeled and actual available costs. It must
not promise guaranteed income, fabricate performance or scale capital based only on a
backtest, confidence score or narrative.

## Change history

| Version | Date | Summary |
| --- | --- | --- |
| `2026.07-ci-cleanroom-testnet-operations-v9` | 2026-07-16 | Repository-wide fail-closed pytest cleanroom, bounded campaign operator CLI, first-real-Testnet runbook and action-bound manual operations. |
| `2026.07-legacy-campaign-operations-v8` | 2026-07-15 | Truth-preserving legacy taxonomy, import-order-safe auth compatibility, Campaign Operations UI/API and gated first-campaign contract. |
| `2026.07-scheduled-execution-evidence-v7` | 2026-07-14 | Scheduled orchestrator, private execution evidence, bounded 10–25 USDT/20-fill campaigns and final reports. |
| `2026.07-automatic-shadow-campaign-v6` | 2026-07-14 | Immutable experiments, actual Bybit reference rules, shadow mode and runtime fill harvesting. |
| `2026.07-experiment-promotion-v5` | 2026-07-14 | Persistent experiment identity, divergence metrics, private startup evidence and manual staged promotion. |
| `2026.07-research-promotion-v4` | 2026-07-14 | Versioned data, funding/impact modeling, walk-forward evaluation and benchmarks. |
| `2026.07-execution-research-v3` | 2026-07-14 | Durable idempotency, startup reconciliation, hard risk limits and event-driven backtesting. |
| `2026.07-safety-foundation-v2` | 2026-07-14 | Mainnet compile lock, canonical execution request, atomic Paper state and truthful CI. |
