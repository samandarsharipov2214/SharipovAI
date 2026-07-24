# SharipovAI Constitution

Version: `2026.07-phase13-trading-execution-v17`  
Status: **Binding development and runtime policy**

This document defines non-negotiable rules for research, Paper, Testnet, controlled
Mainnet, execution, campaigns, evidence, security, CI, deployment and scaling. A
conflicting feature is invalid even when profitable or operationally convenient.

## 1. Capital protection and compile lock

1. Capital preservation has priority over activity, speed and profit.
2. Mainnet execution is unavailable while `MAINNET_EXECUTION_COMPILED=False`.
3. Environment variables, dashboards, Telegram, LLM output, stored state, experiments,
   reports, schedules, scaling authorities and manual decisions cannot override the
   compile lock.
4. Automated keys must not have withdrawal or transfer permission.
5. Martingale, automatic averaging down, uncontrolled leverage increase and all-in
   allocation are forbidden.
6. Promotion, campaign and scaling records are evidence authority only, never direct
   exchange authority.

## 2. Promotion stages

```text
READ_ONLY -> PAPER -> TESTNET -> CONTROLLED_MAINNET -> SCALE
```

Skipping a stage is forbidden.

- `READ_ONLY`: verified market/account reads without exchange writes.
- `PAPER`: virtual capital and realistic fills over verified market evidence.
- `TESTNET`: bounded exchange writes through `ApprovedExecutionRequest`, durable
  idempotency, authenticated private evidence and reconciliation.
- `CONTROLLED_MAINNET`: unavailable in the current build.
- `SCALE`: never automatic and requires measured evidence plus expiring owner approval.

Promotion is blocked by failed, cancelled, queued or skipped CI; missing out-of-sample
evidence; stale private streams; fill divergence; data-quality failure; orphan evidence;
duplicate identity; unresolved order; reconciliation failure; kill-switch state; or
breached loss, drawdown, exposure and correlation limits.

## 3. Canonical decision and execution path

```text
Market Intelligence
  -> Portfolio snapshot
  -> Risk Engine hard limits
  -> Correlation-aware capital allocation
  -> Decision Quality
  -> Security Guard
  -> TradingCandidate validation
  -> Paper execution and benchmark evidence
  -> Campaign authorization where required
  -> Testnet shadow plan
  -> Actual fee and instrument validation
  -> ApprovedExecutionRequest
  -> Durable idempotency reservation
  -> Bybit Testnet executor
  -> Private order topic
  -> Private execution topic
  -> Runtime Fill Harvester
  -> Reconciliation
  -> Fill divergence report
  -> Final report
  -> Manual decision
```

No dashboard, Telegram handler, Learning Engine, strategy, scheduler, operator CLI,
agent or LLM may call an exchange order endpoint directly. The only exchange-write entry
is:

```python
BybitExecutionClient.execute(approved_request)
```

The executor accepts an actual `ApprovedExecutionRequest` object only. Raw symbol/side/
quantity arguments, dictionaries, dashboard payloads and direct calls to the private
submission method are forbidden. The internal submission capability is not an execution
permission that can be serialized or exposed.

## 4. Persistent kill switch

1. `EXECUTION_KILL_SWITCH=1` is the outer hard lock.
2. A durable `PersistentExecutionKillSwitch` is stored in `ProjectDatabase` and survives
   process, container and host restarts.
3. An ambiguous network outcome, accepted response without `orderId`, unresolved intent
   before submission or failed startup reconciliation must latch the persistent switch.
4. Restart, deployment, a new worker, a dashboard action or a successful strategy cannot
   clear the latch.
5. Clearing requires all of the following:
   - environment kill switch explicitly off;
   - restart-safe reconciliation;
   - zero unresolved execution intents;
   - explicit confirmation `I_ACKNOWLEDGE_RECONCILIATION_IS_CLEAN`;
   - authenticated operator identity and persisted audit evidence.
6. A failure to persist the switch blocks execution.

## 5. Idempotency and unknown outcomes

1. Every request has deterministic `sai_...` `orderLinkId` derived from immutable intent.
2. Intent is reserved in `ProjectDatabase` before the network call.
3. The same intent cannot be submitted twice.
4. A timeout after reservation is ambiguous, not a retry signal.
5. Ambiguous requests remain `Submitted`/unresolved until authenticated private evidence
   or explicit reconciliation resolves them.
6. Startup blocks on missing journal evidence, orphan order/fill, identity mismatch,
   quantity mismatch, stale stream or unresolved intent.
7. Retry requires a new explicit attempt identity after the previous attempt is terminal
   and reconciled.
8. Any unresolved reservation blocks every later exchange write, not only the same symbol.

## 6. Private order and execution evidence

The read-only private WebSocket must subscribe to both `order` and `execution`.

- `execId` is write-once;
- exact replay is deduplicated;
- conflicting `execId` reuse blocks reconciliation;
- quantity, price, value, timestamps, maker/taker role and actual fees are persisted;
- partial fills aggregate by `orderLinkId`;
- cumulative order quantity equals summed execution quantity;
- execution without private order is orphan evidence;
- executed private order without execution rows is missing evidence;
- stale streams and missing heartbeats block startup and execution.

A fee that cannot be normalized with verified evidence blocks approval.

## 7. Hard risk and sizing

Hard limits override confidence, consensus, expected profit and manual preference.
Mandatory blocks include stale data, kill switch, invalid instrument, loss/drawdown,
exposure/correlation limits, liquidity floor, missing evidence, non-finite values,
expired request, duplicate, unresolved identity and Mainnet.

| Rule | Default |
| --- | ---: |
| Cash reserve | 20% |
| Maximum total exposure | 80% |
| Maximum one position | 20% |
| Maximum correlated group | 35% |
| Maximum risk per trade | 1% |
| Maximum daily loss | 2% |
| Leverage | 1× |

Missing correlation evidence is not zero correlation. Invalid or non-finite input returns
zero authorized notional. Final notional is the smallest risk, volatility, position,
cluster, campaign/scaling authority and absolute environment capacity.

## 8. Restart-safe Paper trading

Only capital and fills are virtual. Quotes, timestamps, spread, maker/taker fees,
slippage, nonlinear market impact, funding, risk, drawdown and evidence are
production-style.

1. Paper account state is persisted in `ProjectDatabase` with optimistic versioning.
2. A stable `fill_id` is an idempotency key; replay returns the stored fill and cannot
   change cash or position twice.
3. Cash, positions, average entry, fees, slippage, spread cost, funding and realized PnL
   survive restart.
4. Funding accrues using verified rate, elapsed time and configured interval.
5. Buy cannot exceed available virtual cash. Sell cannot exceed the open position.
6. Non-finite, corrupted or incompatible state blocks Paper execution.
7. Fill and funding history is bounded without changing account totals.
8. Synthetic prices, fabricated trades and fake catch-up fills are forbidden.

## 9. Strategy and backtest rules

Mandatory simple strategies in `trading_core` are:

- Buy-and-Hold benchmark;
- Trend Following;
- Breakout;
- Mean Reversion.

Backtests and strategy comparisons:

1. process immutable events in strict `(timestamp, symbol)` order;
2. forbid lookahead, leakage, duplicate bars and random time-series splits;
3. include bid/ask spread, fees, slippage, impact and funding;
4. use the same applicable risk and cost models as Paper/Testnet;
5. record configuration, historical manifest identity and commit SHA;
6. require versioned datasets and visible missing intervals;
7. compare every candidate with Buy-and-Hold and the other mandatory benchmarks;
8. require sequential walk-forward out-of-sample evidence;
9. report return, net PnL, drawdown, fees, slippage, funding, Sharpe, Sortino,
   profit factor, trade count and exposure time;
10. never promote automatically.

A strategy that does not beat Buy-and-Hold after costs, has non-positive net PnL,
insufficient trades or exceeds drawdown gates is not eligible even for Paper review.
A ranking is evidence for review, not execution authority.

## 10. Experiment registry and manual approval

Every candidate requires a persistent experiment registry record with immutable ID,
source commit, validated manifest SHA-256, strategy/backtest configuration, walk-forward
results, benchmarks, data validation, Paper summary, fill divergence, automated report
and explicit manual approval or rejection.

The experiment registry is append-only with optimistic versions. Automation may fail
closed but may never change stage, champion, execution flags, credentials or deployment.
Failed automated gates cannot be overridden.

## 11. Paper/Testnet Shadow Testing

Paper and Testnet share source candidate identity but retain separate observations.
`ShadowExecutionValidator` combines:

- at least 20 matched Paper/Testnet fills;
- zero unmatched Paper fills;
- zero unmatched Testnet fills;
- bounded p95 latency divergence;
- bounded p95 slippage divergence;
- bounded fee divergence;
- bounded partial-fill rate and fill-ratio delta;
- zero unresolved execution intents;
- restart-safe idempotency state;
- inactive persistent kill switch.

The report is immutable SHA-256 evidence. It may return `shadow_eligible=true` only.
`controlled_live_eligible` must remain `false` in this phase. Shadow evidence cannot set
runtime flags, credentials, notional, deployment or Mainnet availability.

## 12. Initial bounded Testnet campaign

- Initial accepted Testnet notional is **10–25 USDT** per order.
- Dynamic instrument filters, private streams and restart reconciliation are mandatory.
- Historical Paper trades cannot be replayed into a new campaign.
- Mainnet execution is compiled out.

A completed campaign requires 20+ actual matched private fills, actual fees, fresh
authenticated streams, restart-safe reconciliation and zero orphan, duplicate,
conflicting, unmatched or unresolved evidence. A sample below 20 remains running, never
successful.

## 13. Campaign Operations and scheduling

1. Scheduler uses only experiments manually approved for `testnet`.
2. State is persisted in `ProjectDatabase`.
3. Worker is disabled by default.
4. At most one global non-terminal campaign authorization exists.
5. Authorization binds campaign ID, experiment ID and scope.
6. A schedule is not raw-order authority.
7. Trades before activation cannot attach to a campaign.
8. Failures are persisted and never blind-retried.
9. Campaign Operations UI is evidence and control-plane visibility only.
10. The operator control plane uses the canonical services and explicit confirmation tokens;
    it cannot install credentials, bypass approval gates, clear the kill switch, enable
    Mainnet or submit a raw exchange order.

## 14. Controlled Testnet scaling

Scaling requires at least two distinct clean campaigns, an eligible SHA-256 protected
plan, no failed gate, increase no greater than `1.5x`, an absolute Testnet ceiling no
greater than `50 USDT`, exact confirmation, one persistent global lock, finite expiry,
canonical execution path, no kill-switch override and Mainnet false.

Expired, revoked, tampered, non-finite or lock-mismatched authority fails closed. Scaling
is never automatic.

## 15. Controlled Mainnet transition

Controlled Mainnet requires a separate pull request and separate audited build where the
compile lock is deliberately changed. Testnet success alone is insufficient.

Before any real-capital order, all gates below are mandatory:

1. complete green CI on the exact release SHA;
2. independent security review of every exchange-write path;
3. proof that only `ApprovedExecutionRequest` reaches the exchange adapter;
4. at least three distinct clean Testnet campaigns and at least 100 matched fills;
5. zero unresolved, orphan, duplicate or conflicting identities across all campaigns;
6. p95 Paper/Testnet latency, slippage, fee and fill-ratio divergence within approved
   thresholds;
7. restart, network partition, database failure and stale-stream crash tests green;
8. persistent kill-switch trip and clear drills green;
9. limited isolated Mainnet subaccount with withdrawal and transfer disabled;
10. no Mainnet credentials in CI, source, logs or Testnet environment;
11. hard initial Mainnet notional and daily loss limits below owner-approved values;
12. legal/regulatory review for the operator jurisdiction;
13. expiring owner authorization bound to SHA, account, symbol scope and maximum notional;
14. manual first-order confirmation and continuous private reconciliation;
15. tested exact-SHA rollback and emergency stop.

The first Controlled Mainnet build must be manual-only, one order at a time, no scheduler,
no autonomous scaling and no credential reuse from Testnet. Any failed gate re-engages the
persistent kill switch and ends the window.

## 16. Final report and decision

The final report combines experiment identity, campaign metrics, benchmark comparison,
fill divergence, private stream health, startup/execution reconciliation, actual fees and
zero identity-failure gates. It stores evidence SHA-256 and returns only
`eligible_for_manual_decision` or `blocked`.

Automatic report generation never removes the separate manual decision. A blocked report
cannot be approved.

## 17. Dashboard, SaaS and API security

1. Sensitive execution routes require an active administrator.
2. Authorization occurs before request-body parsing.
3. Models reject extra fields, invalid symbols and non-finite floats.
4. Browser chat and SaaS APIs are same-origin and use protected cookies.
5. Gemini, exchange and billing secrets never reach the browser.
6. Dashboard uses safe DOM APIs, not `innerHTML`, `insertAdjacentHTML` or `eval`.
7. Missing/stale data is unavailable or blocked, never invented.
8. Dashboard, billing and LLM features cannot create an exchange order or clear a kill
   switch.

## 18. Database, evidence and secrets

`ProjectDatabase` is the canonical source for experiments, reports, schedules, campaigns,
decisions, intents, private state, reconciliation, validation, kill-switch state, Paper
accounts, scaling, performance, audit and project memory.

Secrets, keys, seed phrases, credentials and tokens are forbidden in Git, logs, metrics,
experiments, reports, test artifacts and documentation examples.

## 19. Production audit, deployment and rollback

Production readiness requires canonical checkout, immutable approved full SHA, clean
worktree, dependency audit, compilation, complete pytest, dedicated crash suite, Mainnet
compile lock, engaged production-safe kill switch, auth enabled, database required,
sandbox mode, database health, secret hygiene, atomic post-deploy evidence, persistent
monitoring and exact-SHA rollback to a reviewed ancestor.

Rollback cannot clear execution state or convert unresolved evidence to terminal state.

## 20. CI cleanroom and crash rules

Merge requires dependency install, `pip check`, `pip-audit`, compilation, execution
contract tests, kill-switch tests, idempotency/reconciliation tests, Paper restart tests,
strategy/benchmark tests, private evidence tests, Shadow divergence tests, campaign tests,
research audits and complete pytest.

Mandatory crash scenarios include restart, ambiguous timeout, database failure, duplicate
identity, non-finite data, stale streams, corrupted state, concurrent updates, missing
private evidence, partial persistence, wrong deploy root, failed rollback and SHA mismatch.
A failed, missing, cancelled, queued or skipped workflow is not green.

## 21. Profit and user claims

SharipovAI reports measured results after all modeled and available actual costs. It must
not promise guaranteed income, fabricate performance or scale capital based only on a
backtest, confidence score, subscription tier or narrative.

## Change history

| Version | Date | Summary |
| --- | --- | --- |
| `2026.07-phase13-trading-execution-v17` | 2026-07-22 | Persistent execution kill switch, restart-safe realistic Paper broker, benchmarked Trend/Breakout/Mean Reversion suite, Shadow execution evidence and explicit Controlled Mainnet transition gates. |
| `2026.07-phase11-production-launch-v16` | 2026-07-19 | Exact-SHA preflight/post-deploy/rollback, machine first-campaign gate and expanded crash contracts. |
| `2026.07-phase11-deep-audit-v15` | 2026-07-19 | Scaling integrity, correlation fail-closed sizing and deterministic production audit. |
| `2026.07-ci-cleanroom-testnet-operations-v9` | 2026-07-16 | CI cleanroom, bounded operator CLI and first-real-Testnet runbook. |
| `2026.07-research-promotion-v4` | 2026-07-14 | Versioned data, funding/impact modeling, walk-forward evaluation and benchmarks. |
| `2026.07-execution-research-v3` | 2026-07-14 | Durable idempotency, reconciliation, hard risk and event-driven backtesting. |
