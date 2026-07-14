# SharipovAI Constitution

Version: `2026.07-experiment-promotion-v5`  
Status: **Binding development and runtime policy**

This document defines non-negotiable rules. Code, configuration, dashboards,
AI outputs, CI and deployment automation must obey it. A conflicting feature is
invalid even when it appears profitable.

## 1. Capital protection

1. Capital preservation has priority over activity, speed and profit.
2. Mainnet execution is compiled out at the current development stage.
3. Environment variables, Telegram, dashboard, LLM output, experiment results and
   stored state cannot override the compile lock.
4. Automated API keys must not have withdrawal or transfer permissions.
5. Future live operation requires a separate limited subaccount, expiring manual
   approval and a new audited release. It is not enabled by this branch.
6. No automatic martingale, leverage increase, averaging down or all-in allocation.
7. Promotion records are research authority only. They are never execution authority.

## 2. Promotion stages

```text
READ_ONLY -> PAPER -> TESTNET -> CONTROLLED_MAINNET -> SCALE
```

Skipping a stage is forbidden.

- `READ_ONLY`: public/private reads without exchange writes.
- `PAPER`: virtual capital and fills using verified market evidence.
- `TESTNET`: writes only through an `ApprovedExecutionRequest`, durable idempotency
  reservation and verified private order stream.
- `CONTROLLED_MAINNET`: unavailable while `MAINNET_EXECUTION_COMPILED=False`.
- `SCALE`: never automatic; requires measured live evidence and owner approval.

Promotion is blocked by failed/skipped CI, unresolved orders, stale private stream,
reconciliation errors, insufficient out-of-sample evidence, fill divergence or a
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
  -> ApprovedExecutionRequest
  -> Idempotency reservation
  -> Testnet executor
  -> Private order WebSocket evidence
  -> Startup/runtime reconciliation
  -> Outcome and learning evidence
```

No dashboard, Telegram handler, Learning Engine, agent, strategy or LLM may call
an exchange order endpoint directly. The only exchange write entry is:

```python
BybitExecutionClient.execute(approved_request)
```

## 4. Idempotency and unknown outcomes

1. Every execution request has a deterministic `sai_...` `orderLinkId` derived
   from immutable intent.
2. The intent is reserved in `ProjectDatabase` before the network request.
3. The same intent cannot be submitted twice.
4. Timeout or transport failure after reservation is an ambiguous financial
   outcome, not a retry signal.
5. Ambiguous requests remain unresolved until private order evidence or explicit
   operator reconciliation resolves them.
6. Startup remains blocked for missing journal evidence, orphan private orders,
   identifier mismatch, unresolved intents or an unhealthy private stream.
7. Retry requires a new explicit attempt identity.

## 5. Private order WebSocket gate

Testnet execution requires a read-only authenticated private WebSocket subscribed
to the Bybit `order` topic.

Mandatory evidence:

- feature enabled;
- worker running;
- isolated Testnet credentials configured;
- connected and authenticated;
- `order` topic subscribed;
- fresh persisted heartbeat;
- correct Testnet environment;
- no unresolved reconciliation error.

The stream has no create/amend/cancel capability. A missing or stale heartbeat
blocks Testnet startup. REST acceptance alone is not final execution evidence.

## 6. Hard risk and capital limits

Hard limits always override confidence, consensus, strategy output and expected
profit. Mandatory blocks include stale data, kill switch, invalid instrument,
drawdown/loss limits, total/symbol/correlation exposure, liquidity floor,
maximum positions, missing Evidence, non-finite values, expired requests,
duplicate/unresolved identities and Mainnet environment.

Default research/paper policy:

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

## 7. Paper-trading realism

Only capital and fills are virtual. Quotes, timestamps, maker/taker fees,
bid/ask spread, market impact, slippage, funding, risk, drawdown and Evidence are
production-style inputs.

Paper state must be durable, atomic, revisioned and recoverable. Synthetic prices,
fabricated trades and fake catch-up fills are forbidden.

A paper trade may reach Testnet only when it references a stored canonical
`TradingCandidate`, is recent, matches symbol/side/price and passes fresh validation.

## 8. Backtesting and historical-data integrity

1. Backtests process immutable events in `(timestamp, symbol)` order.
2. Lookahead, future leakage, duplicate bars and random time-series splits are forbidden.
3. Results include spread, fees, slippage, participation impact and funding.
4. Backtest, paper and Testnet converge on shared models, costs, risk and capital logic.
5. Every run records strategy/config version, manifest identity and commit SHA.
6. Historical datasets require a versioned manifest and validation.
7. Missing intervals are visible evidence and are never silently fabricated.
8. A backtest is research evidence, never execution permission.

## 9. Persistent Experiment Registry

Every promotion candidate must exist in the canonical `ExperimentRegistry` with:

- immutable experiment ID;
- source commit SHA;
- validated manifest ID, version and optional SHA-256;
- strategy configuration;
- backtest/cost configuration;
- walk-forward results;
- mandatory benchmark table;
- data-validation result;
- paper summary where applicable;
- Paper/Testnet fill-validation report where applicable;
- automated promotion report;
- explicit manual decision with actor, reason and timestamp.

Experiment lifecycle:

```text
created -> running -> completed -> promotion_pending -> promoted/rejected
```

Results of a promoted experiment are immutable. A rejected experiment may be
re-evaluated only with new Evidence. The registry uses optimistic versions and
append-only events. It does not modify environment variables, deploy code or
change execution mode.

## 10. Research -> PAPER gate

Promotion to PAPER requires all of the following:

- completed persistent experiment;
- valid commit SHA;
- validated versioned data manifest;
- fees, slippage, impact and funding included;
- lookahead disabled;
- at least 6 out-of-sample walk-forward windows;
- at least 60% profitable OOS windows after all costs;
- positive aggregate OOS net PnL;
- maximum drawdown within hard policy;
- positive risk-adjusted score;
- candidate beats buy-and-hold and at least two mandatory benchmarks;
- no single positive window contributes more than 40% of positive OOS PnL;
- no material data-quality warning;
- green dependency audit, critical coverage and complete pytest;
- manual owner review.

Automated evaluation returns only `eligible_for_manual_approval`. Promotion is
persisted only after the exact experiment/stage approval token and a reason are
provided. This does not enable Testnet.

## 11. PAPER -> TESTNET gate

PAPER to TESTNET additionally requires:

- sustained paper evidence across multiple regimes;
- zero hard-risk breaches;
- zero unresolved execution intents;
- at least 20 matched Paper/Testnet fill pairs;
- zero unmatched paper and Testnet fills in the promotion sample;
- p95 latency divergence <= 2000 ms;
- p95 slippage divergence <= 15 bps;
- Testnet partial-fill rate <= 20%;
- maximum fill-ratio divergence <= 0.10;
- fee divergence within documented policy;
- fresh authenticated/subscribed private order WebSocket heartbeat;
- successful startup reconciliation;
- explicit General Controller and owner approval.

Paper/Testnet validation must compare matched stable identities and report latency,
slippage, fee, fill ratio and partial fills. Unmatched or invalid observations are
blocking evidence, not discarded outliers.

Manual approval creates a promotion record only. Testnet execution still requires
its separate default-off environment flags, isolated credentials, stage gate,
kill-switch policy and fresh reconciliation at runtime.

## 12. TESTNET -> CONTROLLED_MAINNET gate

This transition is impossible while `MAINNET_EXECUTION_COMPILED=False`.

A future audited build must additionally require:

- separate limited Mainnet subaccount;
- withdrawal and transfer permissions disabled;
- minimum live-observation period and sample size defined in a new policy version;
- zero duplicate, orphan or unresolved orders;
- verified restart recovery;
- actual fees/slippage consistent with model tolerances;
- daily and weekly loss governors;
- one-position, 1× leverage initial mode;
- expiring owner unlock tied to release, subaccount and maximum notional;
- rollback and emergency kill procedure;
- legal/regulatory review for the operating jurisdiction.

No AI confidence, benchmark rank, manual database edit or dashboard action can
bypass the compile lock.

## 13. Manual approval rules

1. Every promotion target requires a new automated report.
2. Approval token is bound to experiment ID and target stage.
3. Approval requires an authenticated actor and non-empty reason.
4. A failed automated gate cannot be overridden manually.
5. Approval does not alter runtime flags, credentials, capital or deployment.
6. Promotion to a later stage does not erase earlier Evidence.
7. Rejection is persisted with actor, reason and timestamp.

## 14. Canonical architecture

SharipovAI has nine top-level AI organs: General Controller, Market Intelligence,
News Intelligence, Risk Engine, Portfolio Engine, Virtual Execution, Decision
Quality, Learning Engine and Security Guard.

Infrastructure such as registries, storage, monitoring, transport, validation,
idempotency and backtesting is not a new AI organ.

## 15. Learning and strategy changes

Learning may create lessons, proposals and challenger strategies. It may not edit
or deploy production rules, enable exchange writes, increase capital/leverage,
remove Risk/Security vetoes, retry unresolved orders, treat confidence as proof,
optimize against a seen OOS window or omit unfavorable benchmarks.

## 16. Database, Evidence and observability

`ProjectDatabase` is the canonical source of truth for experiment identity,
promotion decisions, execution intents, private order health, validation reports,
audit, learning and project memory. JSON files are bounded backups/caches.

Secrets, seed phrases, keys, credentials and tokens are forbidden in Git, logs,
metrics, experiments, validation reports, Evidence and test artifacts.

## 17. CI and merge rules

Merge requires dependency installation, `pip check`, `pip-audit`, compilation,
critical imports, hard Mainnet lock, execution/idempotency/reconciliation tests,
private-stream tests, risk/capital/backtest tests, manifest and benchmark tests,
experiment/promotion/fill-divergence tests, dashboard auth tests, foundation audits,
critical coverage, complete pytest, retained artifacts, no runtime-state commit and
an explicit rollback path.

A static score, partial suite or AI statement cannot override failed or skipped CI.
Testnet and Mainnet remain disabled by default in CI.

## 18. Profit and user claims

SharipovAI reports measured results after all modeled costs. It must not promise
guaranteed income, fabricate performance or scale capital based only on a backtest,
confidence score or narrative.

## Change history

| Version | Date | Summary |
| --- | --- | --- |
| `2026.07-experiment-promotion-v5` | 2026-07-14 | Persistent experiment identity, Paper/Testnet divergence metrics, mandatory private WebSocket startup evidence and manual staged promotion decisions. |
| `2026.07-research-promotion-v4` | 2026-07-14 | Versioned Parquet/DuckDB data, funding/impact modeling, walk-forward evaluation, benchmarks and operational metrics. |
| `2026.07-execution-research-v3` | 2026-07-14 | Durable idempotency, startup reconciliation, hard risk/correlation limits and shared event-driven backtesting. |
| `2026.07-safety-foundation-v2` | 2026-07-14 | Mainnet compile lock, canonical execution request, atomic paper state and truthful CI. |
