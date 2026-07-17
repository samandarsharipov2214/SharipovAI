# SharipovAI Constitution

Version: `2026.07-production-readiness-first-campaign-v10`  
Status: **Binding development, deployment and runtime policy**

A conflicting feature is invalid even when it appears profitable, convenient or operationally urgent.

## 1. Capital protection

1. Capital preservation has priority over activity, speed and profit.
2. Mainnet execution remains unavailable while `MAINNET_EXECUTION_COMPILED=False`.
3. Environment variables, dashboard actions, Telegram, LLM output, stored state, experiments, schedules, reports and manual decisions cannot override the compile lock.
4. Automated keys must not have withdrawal or transfer permissions.
5. Automatic martingale, averaging down, leverage increase and all-in allocation are forbidden.
6. Promotion and campaign records are evidence authority only, never direct execution authority.

## 2. Promotion stages

```text
READ_ONLY -> PAPER -> TESTNET -> CONTROLLED_MAINNET -> SCALE
```

Skipping a stage is forbidden. `CONTROLLED_MAINNET` is unavailable while the compile lock is false. Automated gates require a separate manual decision, and failed gates cannot be manually overridden.

## 3. Canonical execution path

```text
Market Intelligence
  -> Portfolio snapshot
  -> Risk Engine hard limits
  -> Capital allocation
  -> Decision Quality
  -> Security Guard
  -> TradingCandidate validation
  -> Paper execution
  -> active bounded campaign authorization
  -> actual Bybit fee/instrument validation
  -> ApprovedExecutionRequest
  -> durable idempotency reservation
  -> Bybit Testnet executor
  -> private order + execution topics
  -> reconciliation
  -> Runtime Fill Harvester
  -> immutable final report
  -> manual decision
```

No dashboard, Telegram handler, Learning Engine, agent, strategy, scheduler, CLI or LLM may call an exchange order endpoint directly. The only write entry is:

```python
BybitExecutionClient.execute(approved_request)
```

## 4. Idempotency and unknown outcomes

1. Every request has a deterministic `sai_...` `orderLinkId` derived from immutable intent.
2. Intent is reserved in `ProjectDatabase` before the network request.
3. The same intent cannot be submitted twice.
4. Timeout after reservation is an ambiguous financial outcome, not a retry signal.
5. Ambiguous requests remain unresolved until authenticated private evidence or explicit reconciliation resolves them.
6. Startup is blocked by missing journal evidence, orphan fills, identifier/quantity mismatch or unresolved intent.
7. Retry requires a new explicit attempt identity.

## 5. Private execution evidence

The authenticated read-only stream must subscribe to both `order` and `execution`.

Mandatory readiness:

- isolated Testnet credentials;
- correct sandbox endpoint;
- connected/authenticated worker;
- both topics subscribed and heartbeat fresh;
- zero unresolved reconciliation errors.

`execId` is write-once. Exact replay is deduplicated. Conflicting reuse blocks reconciliation. Quantity, price, value, time, maker/taker state, fees and fee currency are persisted. Partial fills aggregate by `orderLinkId`. Executions without private orders and executed private orders without execution rows are blocking evidence.

## 6. Hard risk and capital limits

Hard limits override confidence, consensus, strategy output and expected profit. Mandatory blocks include stale data, kill switch, invalid instrument, loss/drawdown, exposure/correlation limits, liquidity floor, maximum positions, missing evidence, non-finite values, expired requests, duplicates, unresolved identities and Mainnet.

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

## 7. Research and data integrity

Only capital and fills are virtual in Paper mode. Quotes, timestamps, spread, fees, slippage, impact, funding, risk and drawdown remain production-style. Synthetic prices, fabricated trades and fake catch-up fills are forbidden.

Backtests must:

1. process immutable events in `(timestamp, symbol)` order;
2. forbid lookahead and random time-series splits;
3. include spread, fees, slippage, impact and funding;
4. record config, data manifest and commit SHA;
5. keep gaps visible;
6. compare mandatory benchmarks;
7. require sequential walk-forward out-of-sample evidence;
8. remain evidence, never permission to trade.

## 8. Experiments and promotion

Every candidate requires persistent experiment identity, source commit, validated data manifest, config, walk-forward results, benchmarks, Paper summary, fill validation, automated report and manual decision.

The registry uses optimistic versions and append-only events. Automatic experiments may fail closed but may never change execution flags, deployment, capital or Mainnet state.

Manual decisions require current automated evidence, action-bound token, actor and reason. They cannot override failed gates.

## 9. Bounded Testnet policy

- Spot Testnet only.
- Per-order accepted notional: **10–25 USDT**.
- Dynamic filters, private streams and startup reconciliation are mandatory.
- Historical Paper trades cannot be replayed into a new campaign.
- Mainnet remains compiled out.

Completion requires:

| Gate | Requirement |
| --- | ---: |
| Matched Paper/Testnet fills | 20+ |
| Unmatched Paper fills | 0 |
| Unmatched Testnet fills | 0 |
| Orphan executions | 0 |
| Duplicate/conflicting identities | 0 |
| Unresolved execution intents | 0 |
| Actual private execution fees | Present |
| Private stream | Fresh |
| Startup/execution reconciliation | Restart-safe |

Any orphan, duplicate, unresolved, reconciliation or out-of-range notional failure hard-blocks the campaign. Fewer than 20 matched fills remains incomplete.

## 10. Single campaign authorization

1. A scheduler may use only an experiment manually approved for `testnet`.
2. At most one global non-terminal campaign exists.
3. Campaign authorization is bound to campaign, experiment and scope.
4. Authorization does not expose raw order authority.
5. Trades created before activation cannot join a new campaign.
6. Failures are persisted and never blind-retried.
7. Scheduler actions cannot alter runtime flags or Mainnet availability.

## 11. Production deployment policy

1. `deploy/vps/.env.vps` is permanently production-safe: kill switch on, Testnet writes off and release gate blocked.
2. Testnet credentials and green release authorization belong only in ignored `deploy/vps/.env.testnet-campaign` or an equivalent secret manager.
3. Production and campaign env files must be mode `0600`.
4. Configuration is parsed as data; deployment scripts must not shell-source secret files.
5. A candidate deployment requires a verified backup before mutation.
6. Rendered Compose must be validated before start.
7. Health endpoint, container health and canonical database health must pass after start.
8. Failure must restore the previous reviewed code/runtime or production-safe Compose.
9. Recovery must preserve corrupt data and hashes before replacement.
10. Mainnet credentials are forbidden on the bounded Testnet VPS.
11. Container security must retain non-root execution, dropped capabilities, `no-new-privileges`, bounded logs and healthchecks unless a documented platform constraint proves otherwise.

## 12. Testnet runtime transition

Entering bounded Testnet mode requires all of:

```text
complete green required CI
PHASE6_TESTNET_RELEASE_GATE=green
isolated Testnet credentials
I_APPROVE_BOUNDED_TESTNET_RUNTIME_DEPLOYMENT
```

The transition script may enable only audited Testnet flags through the explicit Compose override. It must not mutate the production-safe base env file.

Leaving the window requires:

```text
I_APPROVE_RESTORE_PRODUCTION_KILL_SWITCH
```

After completion, block, timeout or abort, production locks must be restored immediately.

## 13. First real campaign runner

`scripts/first_testnet_campaign.py` may call canonical campaign services only. It:

- requires exact start/cycle/report confirmations;
- has finite cycle and time limits;
- can resume only the same campaign without bypassing other blockers;
- writes an append-only evidence bundle;
- returns success only for completed, clean, actual private-fill evidence;
- cannot change configuration, credentials, deployment, capital or Mainnet.

A campaign row, REST acceptance, Paper-only fill, screenshot, synthetic fixture or copied JSON is not real execution evidence.

## 14. Critical monitoring and alerting

Critical campaign events must be persisted in `ProjectDatabase` with deduplication and automatic resolution history.

Mandatory signals:

- more than one active campaign;
- kill switch engaged during an active campaign;
- non-restart-safe reconciliation;
- stale/unready private stream;
- blocked campaign;
- orphan, duplicate, unresolved, reconciliation or notional gate failure;
- orchestrator errors.

External delivery is optional; persistent evidence is mandatory. Delivery must be sanitized, HTTPS-only for webhooks and must never contain secrets. Delivery failure cannot erase or resolve an alert.

Alerts are observation authority only. They may not place orders, disable the kill switch or approve promotion.

## 15. Operator control plane

Campaign APIs and UI require authenticated admin access for mutations. They may expose schedules, readiness, cycles, reports, decisions and alert evaluation but never a raw order primitive.

All state-changing operations must route through canonical services, preserve actor identity and return factual blockers.

## 16. Final report and decision

The final report combines experiment identity, campaign metrics, divergence, private stream health, startup/execution reconciliation, actual fees and zero identity-failure gates. It stores an evidence SHA-256 and returns only `eligible_for_manual_decision` or `blocked`.

Automatic report generation never removes the separate manual decision. A blocked report cannot be approved. A decision cannot deploy code, allocate capital or enable Mainnet.

## 17. Canonical architecture

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

Storage, transport, schedulers, registries, validation, observability, backtesting and campaign orchestration are infrastructure, not additional AI organs.

## 18. Learning and compatibility

Learning may create lessons, proposals and challengers. It may not deploy rules, enable exchange writes, increase capital/leverage, remove Risk/Security vetoes, retry unresolved orders or appoint a champion without approved evidence.

Compatibility adapters may preserve callable names only while routing to the canonical implementation. They may not restore raw-order entry points, Mainnet unlock behavior, synthetic sources or obsolete renderer ownership.

## 19. CI and merge rules

Merge requires dependency audit, compilation, critical imports, hard Mainnet lock, execution/idempotency/reconciliation tests, private stream tests, campaign and alert tests, deployment-script contracts, UI contracts, foundation audits, critical coverage, complete pytest and retained artifacts.

Every pytest process in CI must begin from a fail-closed cleanroom. Unknown full-suite failures are regressions. Classification cannot turn failed, missing, queued or skipped CI green.

## 20. Database, evidence and secrets

`ProjectDatabase` is the canonical source of truth for experiments, schedules, campaigns, reports, decisions, intents, private order/execution state, reconciliation, validation, alerts, learning and project memory.

Secrets, keys, seed phrases, credentials and tokens are forbidden in Git, logs, metrics, experiments, reports, test artifacts and documentation examples.

## 21. Profit and user claims

SharipovAI reports measured results after modeled and actual available costs. It must not promise guaranteed income, fabricate performance or scale capital based only on a backtest, confidence score or narrative.

## Change history

| Version | Date | Summary |
| --- | --- | --- |
| `2026.07-production-readiness-first-campaign-v10` | 2026-07-18 | Hardened production/Testnet deployment separation, rollback smoke checks, finite real-campaign evidence runner, persistent critical alerts and responsive Campaign Operations UI. |
| `2026.07-ci-cleanroom-testnet-operations-v9` | 2026-07-16 | Fail-closed CI cleanroom, bounded campaign CLI and first-campaign runbook. |
| `2026.07-legacy-campaign-operations-v8` | 2026-07 | Campaign operations and legacy contract stabilization. |
