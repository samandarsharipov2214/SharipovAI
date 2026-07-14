# SharipovAI Constitution

Version: `2026.07-scheduled-execution-evidence-v7`  
Status: **Binding development and runtime policy**

This document defines non-negotiable rules for code, AI organs, configuration,
dashboards, CI, experiments, campaigns and deployment. A conflicting feature is
invalid even when it appears profitable.

## 1. Capital protection

1. Capital preservation has priority over activity, speed and profit.
2. Mainnet execution is compiled out while `MAINNET_EXECUTION_COMPILED=False`.
3. Environment variables, Telegram, dashboard, LLM output, stored state,
   experiment results, schedules and campaign reports cannot override the compile lock.
4. Automated API keys must not have withdrawal or transfer permissions.
5. Future live operation requires a separate limited subaccount, a new audited
   release and an expiring owner approval.
6. Automatic martingale, leverage increase, averaging down and all-in allocation
   are forbidden.
7. Promotion, leadership and campaign records are evidence authority only. They are
   never direct execution authority.

## 2. Promotion stages

```text
READ_ONLY -> PAPER -> TESTNET -> CONTROLLED_MAINNET -> SCALE
```

Skipping a stage is forbidden.

- `READ_ONLY`: public/private reads without exchange writes.
- `PAPER`: virtual capital and fills using verified market evidence.
- `TESTNET`: writes only through `ApprovedExecutionRequest`, durable idempotency,
  bounded shadow mode, actual Bybit filters and authenticated private evidence.
- `CONTROLLED_MAINNET`: unavailable while `MAINNET_EXECUTION_COMPILED=False`.
- `SCALE`: never automatic and requires measured live evidence plus owner approval.

Promotion is blocked by failed or skipped CI, unresolved identities, stale private
stream, orphan evidence, duplicate execution identities, reconciliation errors,
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

No dashboard, Telegram handler, Learning Engine, agent, strategy, scheduler or LLM
may call an exchange order endpoint directly. The only exchange write entry is:

```python
BybitExecutionClient.execute(approved_request)
```

## 4. Idempotency and unknown outcomes

1. Every request has a deterministic `sai_...` `orderLinkId` derived from immutable intent.
2. Intent is reserved in `ProjectDatabase` before the network request.
3. The same intent cannot be submitted twice.
4. A timeout after reservation is an ambiguous financial outcome, not a retry signal.
5. Ambiguous requests stay unresolved until authenticated private evidence or an
   explicit operator reconciliation resolves them.
6. Startup remains blocked for missing journal evidence, orphan orders/fills,
   identifier mismatch, quantity mismatch or unresolved intent.
7. Retry requires a new explicit attempt identity.

## 5. Private order WebSocket gate

The private order websocket gate is read-only and must subscribe to both:

```text
order
execution
```

Mandatory evidence:

- feature enabled;
- worker running;
- isolated Testnet credentials configured;
- connected and authenticated;
- `order` topic subscribed;
- `execution` topic subscribed;
- fresh persisted heartbeat;
- correct Testnet environment;
- no unresolved order or execution reconciliation error.

The stream has no create/amend/cancel capability. REST acceptance alone is not
final evidence. A missing or stale heartbeat blocks Testnet startup.

## 6. Private execution topic

The private execution topic is the canonical source for actual fill evidence:

- `execId` is write-once;
- exact WebSocket replay is deduplicated;
- conflicting reuse of an `execId` blocks reconciliation;
- `execQty`, `execPrice`, `execValue`, `execTime`, `isMaker`, `feeRate`,
  `execFee` and `feeCurrency` are persisted;
- multiple partial fills are aggregated by `orderLinkId`;
- order cumulative quantity must equal summed execution quantity;
- an execution without a corresponding private order is orphan evidence;
- an executed private order without execution rows is missing evidence.

Actual fee amount and currency must be retained. A fee that cannot be normalized
without a verified conversion must block fee-divergence approval rather than be guessed.

## 7. Hard risk and capital limits

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

Soft risk may only reduce size: `LOW=1.0`, `MEDIUM=0.6`, `HIGH=0.25`,
`CRITICAL=0.0`.

## 8. Paper-trading realism

Only capital and fills are virtual. Quotes, timestamps, spread, maker/taker fees,
slippage, market impact, funding, risk, drawdown and evidence are production-style.

Paper state must be durable, atomic, revisioned and recoverable. Synthetic prices,
fabricated trades and fake catch-up fills are forbidden.

A Paper trade may reach Testnet only when it references a canonical stored
`TradingCandidate`, is recent, matches symbol/side/price and passes fresh validation.

## 9. Backtesting and historical-data integrity

1. Backtests process immutable events in `(timestamp, symbol)` order.
2. Lookahead, future leakage, duplicate bars and random time-series splits are forbidden.
3. Results include spread, fees, slippage, participation impact and funding.
4. Backtest, Paper and Testnet converge on shared models, costs and risk rules.
5. Every run records config, manifest identity and commit SHA.
6. Historical datasets require a versioned manifest and validation.
7. Missing intervals remain visible and are never fabricated.
8. Every candidate is compared with buy-and-hold, trend, breakout and mean reversion.
9. Sequential walk-forward out-of-sample evidence is mandatory for a promotion gate.
10. A backtest is evidence, never permission to trade.

## 10. Persistent Experiment Registry

Every promotion candidate requires a persistent experiment registry record with:

- immutable experiment ID;
- source commit SHA;
- validated manifest ID/version/SHA-256;
- strategy and backtest configuration;
- walk-forward results;
- mandatory benchmark table;
- data-validation result;
- Paper summary where applicable;
- Paper/Testnet fill validation;
- automated promotion report;
- explicit manual decision.

```text
created -> running -> completed -> promotion_pending -> promoted/rejected
```

The registry uses optimistic versions and append-only events. It cannot modify
runtime flags, credentials, capital or deployment.

## 11. Automatic experiment execution

The Automatic Experiment Runner must validate the manifest, derive one deterministic
fingerprint, refuse duplicate commit/manifest/config experiments, run walk-forward
plus all benchmarks and save validation/walk-forward/benchmark/summary results in a
write-once namespace with SHA-256 references.

An automatic experiment may fail closed. It may never change stage, champion,
execution flag or deployment automatically.

## 12. Actual Bybit reference-data rules

Testnet shadow execution must use read-only current Bybit evidence:

- account-specific fee tier from `/v5/account/fee-rate`;
- `tickSize`, `qtyStep`, minimum quantity, minimum notional and maximum market
  quantity from `/v5/market/instruments-info`;
- environment, category, source and expiration timestamp;
- bounded `ProjectDatabase` cache.

Quantity is always rounded down to `qtyStep`. Rounding up, guessing a minimum or
using a screenshot/static table as execution authority is forbidden.

## 13. Testnet shadow mode

Paper and Testnet share one source candidate but retain separate execution observations.

- Paper sizing/accounting is unchanged.
- Testnet receives a fresh candidate derived from the same evidence.
- `source_candidate_id`, Testnet candidate ID and `shadow_pair_id` are persisted.
- Testnet notional cannot exceed 25 USDT in this build.
- Dynamic Bybit filters, private stream and startup reconciliation are mandatory.
- Historical Paper trades are not replayed into a new campaign.
- Mainnet remains compiled out.

## 14. Scheduled Campaign Orchestrator

The Scheduled Campaign Orchestrator may schedule only an experiment already manually
approved for the exact `testnet` stage.

Rules:

1. scheduler state is persisted in `ProjectDatabase`;
2. minimum schedule interval is one minute;
3. the worker is disabled by default;
4. a due schedule creates a bounded campaign authorization, not raw order authority;
5. one canonical bridge and one canonical harvester are reused;
6. a campaign authorization is bound to campaign ID, experiment ID and strategy scope;
7. a trade created before campaign activation cannot be attached to that campaign;
8. scheduler and campaign actions never change runtime flags or Mainnet availability;
9. failures are persisted and never retried as blind exchange submissions.

## 15. Testnet Shadow Campaign

A bounded Testnet Shadow Campaign must satisfy all of the following:

- each accepted Testnet order is within **10–25 USDT**;
- at least **20 matched** Paper/Testnet fills;
- zero unmatched Paper fills;
- zero unmatched Testnet fills;
- **zero orphan** orders or execution fills;
- zero duplicate order identities;
- zero conflicting duplicate execution identities;
- zero unresolved execution intents;
- actual private execution fees available;
- fresh private order/execution stream;
- successful startup and order/execution reconciliation;
- existing latency, slippage, fill-ratio and partial-fill limits.

Any duplicate, orphan, unresolved identity or out-of-range notional hard-blocks the
campaign. A pending sample below 20 matched fills remains running, not successful.

## 16. Runtime Fill Harvester

The Runtime Fill Harvester joins canonical Paper trade, campaign-bound bridge record,
`orderLinkId`, private order lifecycle and private execution rows.

It persists latency, slippage, actual fee, fill ratio, partial-fill and unmatched-fill
divergence. Report identity is derived from immutable execution evidence including
`execId` values. An unchanged evidence set cannot create a conflicting report.

The harvester is read-only with respect to exchange execution and cannot promote a strategy.

## 17. Final Promotion Report

The Final Promotion Report Engine runs only for a completed campaign and combines:

- experiment identity and research evidence;
- campaign metrics;
- Paper/Testnet divergence;
- private stream health;
- startup reconciliation;
- order/execution reconciliation;
- actual execution fees;
- zero orphan/duplicate/unresolved gates.

The report stores an evidence SHA-256 and returns only
`eligible_for_manual_decision` or `blocked`. It cannot change runtime flags,
credentials, capital, deployment, champion or Mainnet state.

## 18. Champion / Challenger

Each bounded scope has exactly one champion and zero or more challengers.

- A challenger requires completed experiment evidence.
- A champion requires an experiment promoted for the exact target stage.
- Automated gates and manual experiment approval must both be present.
- Leadership requires `PROMOTE:<scope>:<experiment>:<stage>`.
- Actor, reason, previous champion, timestamp and evidence SHA-256 are persisted.
- Replaced champions remain in history.
- The `/champion-challenger` page is an administrative evidence UI only.
- Champion selection cannot deploy code, enable Testnet/Mainnet or change capital.

## 19. Research -> PAPER gate

Promotion to PAPER requires validated data, at least six out-of-sample walk-forward
windows, at least 60% profitable OOS windows, positive all-cost net PnL, controlled
drawdown, positive risk-adjusted score, mandatory benchmark performance, no material
data warning, green CI and manual owner review.

## 20. PAPER -> TESTNET gate

PAPER -> TESTNET requires sustained Paper evidence, zero hard-risk breaches, zero
unresolved intents, at least 20 matched fills, zero unmatched fills, policy-compliant
latency/slippage/partial-fill/fill-ratio/fee divergence, fresh private topics,
successful reconciliation and explicit General Controller plus owner approval.

Manual approval creates a record only. Runtime execution still requires separate
default-off flags, isolated credentials, kill switch and fresh evidence.

## 21. TESTNET -> CONTROLLED_MAINNET gate

TESTNET -> CONTROLLED_MAINNET is impossible while `MAINNET_EXECUTION_COMPILED=False`.

A future audited build must additionally require a limited subaccount, disabled
withdrawal/transfer permissions, a defined observation period, zero orphan/duplicate/
unresolved orders, restart recovery, actual cost consistency, loss governors, 1×
initial leverage, expiring owner unlock, rollback procedure and legal review.

## 22. Manual approval rules

1. Every promotion target requires a current automated report.
2. Approval token is bound to experiment and stage.
3. Champion approval is additionally bound to strategy scope.
4. Approval requires an authenticated actor and non-empty reason.
5. Failed automated gates cannot be overridden manually.
6. Approval does not alter flags, credentials, capital or deployment.
7. Rejection is persisted with actor, reason and timestamp.

## 23. Canonical architecture

SharipovAI has nine top-level AI organs: General Controller, Market Intelligence,
News Intelligence, Risk Engine, Portfolio Engine, Virtual Execution, Decision
Quality, Learning Engine and Security Guard.

Storage, transport, scheduler, registries, validation, observability, backtesting and
campaign orchestration are infrastructure, not additional AI organs.

## 24. Learning and strategy changes

Learning may create lessons, proposals and challengers. It may not deploy production
rules, enable exchange writes, increase capital/leverage, remove Risk/Security vetoes,
retry unresolved orders, optimize against seen OOS data or appoint a champion without
approved evidence.

## 25. Database, evidence and observability

`ProjectDatabase` is the canonical source of truth for experiments, immutable results,
schedules, campaigns, final reports, leadership, intents, private order/execution
state, reconciliation, validation, audit, learning and project memory.

Secrets, keys, seed phrases, credentials and tokens are forbidden in Git, logs,
metrics, experiments, reports and test artifacts.

## 26. CI and merge rules

Merge requires dependency installation, `pip check`, `pip-audit`, compilation,
critical imports, hard Mainnet lock, idempotency/reconciliation tests, private order
and execution tests, campaign scheduler/policy tests, actual fee harvester tests,
leadership dashboard tests, experiment/risk/research tests, foundation audits,
critical coverage, complete pytest, retained artifacts and rollback instructions.

A static score, partial suite, queued check or AI statement cannot override failed or
skipped CI. Testnet and Mainnet remain disabled by default in CI.

## 27. Profit and user claims

SharipovAI reports measured results after all modeled and actual available costs. It
must not promise guaranteed income, fabricate performance or scale capital based only
on a backtest, confidence score or narrative.

## Change history

| Version | Date | Summary |
| --- | --- | --- |
| `2026.07-scheduled-execution-evidence-v7` | 2026-07-14 | Scheduled Campaign Orchestrator, private execution topic with actual fees and partial fills, bounded 10–25 USDT/20-fill campaigns, final promotion reports and Champion / Challenger UI. |
| `2026.07-automatic-shadow-campaign-v6` | 2026-07-14 | Automatic immutable experiments, actual Bybit fee/instrument rules, bounded shadow mode, runtime fill harvesting and evidence-gated leadership. |
| `2026.07-experiment-promotion-v5` | 2026-07-14 | Persistent experiment identity, divergence metrics, private WebSocket startup evidence and manual staged promotion. |
| `2026.07-research-promotion-v4` | 2026-07-14 | Versioned Parquet/DuckDB data, funding/impact modeling, walk-forward evaluation and benchmarks. |
| `2026.07-execution-research-v3` | 2026-07-14 | Durable idempotency, startup reconciliation, hard risk/correlation limits and event-driven backtesting. |
| `2026.07-safety-foundation-v2` | 2026-07-14 | Mainnet compile lock, canonical execution request, atomic Paper state and truthful CI. |
