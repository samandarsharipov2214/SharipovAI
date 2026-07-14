# SharipovAI Constitution

Version: `2026.07-research-promotion-v4`  
Status: **Binding development and runtime policy**

This document defines non-negotiable rules. Code, configuration, dashboards,
AI outputs, CI and deployment automation must obey it. A conflicting feature is
invalid even when it appears profitable.

## 1. Capital protection

1. Capital preservation has priority over activity, speed and profit.
2. Mainnet execution is compiled out at the current development stage.
3. Environment variables, Telegram, dashboard, LLM output and stored state cannot
   override the compile lock.
4. Automated API keys must not have withdrawal or transfer permissions.
5. Future live operation requires a separate limited subaccount, expiring manual
   approval and a new audited release. It is not enabled by this branch.
6. No automatic martingale, leverage increase, averaging down or all-in allocation.

## 2. Promotion stages

```text
READ_ONLY -> PAPER -> TESTNET -> CONTROLLED_MAINNET -> SCALE
```

Skipping a stage is forbidden.

- `READ_ONLY`: public/private reads without exchange writes.
- `PAPER`: virtual capital and fills using verified market evidence.
- `TESTNET`: writes only through an `ApprovedExecutionRequest` and durable
  idempotency reservation.
- `CONTROLLED_MAINNET`: unavailable while `MAINNET_EXECUTION_COMPILED=False`.
- `SCALE`: never automatic; requires measured live evidence and owner approval.

Promotion is blocked by failed/skipped CI, unresolved orders, reconciliation
errors, insufficient out-of-sample evidence or a breached drawdown/loss limit.

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
  -> Private order state
  -> Startup/runtime reconciliation
  -> Outcome and learning evidence
```

No dashboard, Telegram handler, Learning Engine, agent, strategy or LLM may call
an exchange order endpoint directly. The legacy `place_market_order()` entry
point is removed. The only exchange write entry is:

```python
BybitExecutionClient.execute(approved_request)
```

## 4. Idempotency and unknown outcomes

1. Every execution request has a deterministic `sai_...` `orderLinkId` derived
   from the immutable intent.
2. The intent is reserved in the canonical `ProjectDatabase` before the network
   request.
3. The same intent cannot be submitted twice.
4. A timeout or transport failure after reservation is an **ambiguous financial
   outcome**, not a normal retry signal.
5. Ambiguous requests remain `Submitted`/unresolved until private order evidence
   or explicit operator reconciliation resolves them.
6. Startup execution remains blocked when reconciliation reports missing journal
   evidence, orphan private orders, identifier mismatch or unresolved intents.
7. A retry requires a new explicit attempt identity and must never reuse an
   unresolved attempt blindly.

## 5. Hard risk limits

Hard limits always override confidence, consensus, strategy output and expected
profit. Mandatory blocks include:

- active kill switch;
- stale or future-dated market data;
- invalid/missing instrument specification;
- portfolio drawdown at or above the configured limit;
- daily or weekly loss limit;
- total, symbol or correlated exposure limit;
- maximum open-position limit;
- liquidity below the minimum floor;
- missing portfolio, fee, risk or Evidence identifiers;
- non-finite values;
- expired candidate or execution request;
- duplicate/unresolved order identity;
- Mainnet environment.

The default research/paper capital policy is:

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

Soft risk may only reduce position size: `LOW=1.0`, `MEDIUM=0.6`,
`HIGH=0.25`, `CRITICAL=0.0`.

## 6. Paper-trading realism

Only capital and fills are virtual. Quotes, timestamps, maker/taker fees,
bid/ask spread, nonlinear market impact, slippage, funding, risk, drawdown and
Evidence must be treated as production inputs.

Paper state must be durable, atomic, revisioned and recoverable from a
last-known-good backup. Synthetic historical prices, fabricated trades and fake
catch-up fills are forbidden.

A paper trade may reach Testnet only when it references a stored canonical
`TradingCandidate`, is recent enough for mirroring, matches symbol/side/price and
passes fresh validation again.

## 7. Backtesting and historical-data integrity

1. Backtests process immutable events in chronological `(timestamp, symbol)` order.
2. Lookahead, future leakage, duplicate bars and random time-series train/test
   splits are forbidden.
3. Results include bid/ask spread, maker/taker fees, deterministic slippage,
   participation-based market impact and funding where applicable.
4. Backtest, paper and Testnet must converge on shared domain models, cost logic,
   risk limits and capital allocation.
5. Every run records strategy/config version, data provenance and commit SHA.
6. Historical datasets require a versioned manifest with venue, market type,
   symbols, interval, time range, row count, schema and optional SHA-256 hashes.
7. Parquet data must pass schema, range, symbol, duplicate and price-integrity
   validation before it can create `MarketEvent` objects.
8. Missing intervals are visible evidence and must never be silently fabricated.
9. A backtest is research evidence, never permission to enable Mainnet.

## 8. Research promotion gate

A candidate strategy may move from research into sustained PAPER evaluation only
when every mandatory gate below passes. Passing these gates does not enable
Testnet or Mainnet automatically.

### 8.1 Required evidence

- a validated, versioned historical-data manifest;
- reproducible configuration and source commit SHA;
- spread, maker/taker fees, slippage, market impact and funding included;
- no lookahead or future-data access;
- sequential out-of-sample walk-forward evaluation;
- mandatory comparison with `buy-and-hold`, trend-following, breakout and
  mean-reversion benchmarks;
- complete CI, coverage, dependency audit and retained result artifacts.

### 8.2 Minimum quantitative gate

Unless a stricter instrument-specific policy exists, promotion requires:

- at least **6** completed out-of-sample walk-forward windows;
- at least **60%** profitable out-of-sample windows after all modeled costs;
- positive aggregate out-of-sample net PnL;
- maximum drawdown within the active hard risk policy;
- positive risk-adjusted score;
- the candidate must beat buy-and-hold and at least two of the four mandatory
  benchmarks on the same data and cost assumptions;
- no single walk-forward window may contribute more than **40%** of total positive
  out-of-sample PnL;
- no unresolved data-quality warning that could materially improve the result.

A threshold may be made stricter by Risk Engine or General Controller. It may not
be weakened automatically by a strategy, AI agent, dashboard or optimizer.

### 8.3 Paper and Testnet promotion

Research-to-PAPER additionally requires human review of the manifest, strategy
code, benchmark table and drawdown path. PAPER-to-TESTNET requires:

- sustained paper evidence over multiple market regimes;
- measured paper-versus-model fill divergence within an explicitly documented
  tolerance;
- zero unresolved execution intents;
- successful startup reconciliation;
- no hard risk breach;
- explicit General Controller and owner approval.

TESTNET-to-CONTROLLED_MAINNET remains impossible while
`MAINNET_EXECUTION_COMPILED=False`. No metric, benchmark rank or AI confidence may
override that compile lock.

## 9. Canonical architecture

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

New capabilities extend an existing owner unless the responsibility is genuinely
unique. Interfaces, storage, monitoring, transport, idempotency and backtesting
are infrastructure, not new AI organs.

## 10. Learning and strategy changes

Learning may create lessons, proposals and challenger strategies. It may not:

- edit or deploy production trading rules automatically;
- enable exchange writes;
- increase capital or leverage;
- remove Risk/Security vetoes;
- reinterpret an unresolved order as failed and retry it;
- treat confidence as proof of profitability;
- optimize against the out-of-sample window after seeing its results;
- select only favorable benchmarks or omit buy-and-hold.

Promotion requires reproducible tests, out-of-sample evidence, champion/challenger
comparison and General Controller approval.

## 11. Database, Evidence and observability

`ProjectDatabase` is the canonical source of truth for execution intents, order
state, audit, learning and project memory. JSON files are bounded backups/caches,
not execution authority.

Operational metrics and structured logs must describe actual runtime state. They
must not claim that execution is enabled when the kill switch, stage gate or
compile lock blocks it. Metrics are read-only and cannot trigger trading.

Secrets, seed phrases, private keys, API secrets and credentials are forbidden in
Git, logs, Prometheus labels, Evidence, change ledgers, test artifacts and prompts.
Structured logging must redact credential-like fields.

## 12. CI and merge rules

A change is mergeable only when all relevant factual gates complete:

- dependency installation and `pip check`;
- `pip-audit` without unapproved vulnerabilities;
- Python compilation;
- critical imports;
- hard Mainnet-lock verification;
- execution/idempotency/reconciliation tests;
- risk/capital/backtesting safety tests;
- funding, walk-forward and benchmark tests;
- historical manifest/Parquet validation tests;
- dashboard auth, execution-status and observability tests;
- execution and research foundation audits;
- critical-module coverage threshold;
- complete pytest suite;
- test and coverage artifacts retained;
- no secret/runtime-state commit;
- explicit rollback path.

A static score, partial suite or AI statement cannot override a failed or skipped
full suite. Testnet and Mainnet remain disabled by default in CI.

## 13. Profit and user claims

SharipovAI reports measured results after all modeled costs. It must not promise
guaranteed income, fabricate performance or scale capital based only on a
backtest, confidence score or narrative.

## Change history

| Version | Date | Summary |
| --- | --- | --- |
| `2026.07-research-promotion-v4` | 2026-07-14 | Versioned Parquet/DuckDB data, funding and market-impact modeling, walk-forward evaluation, mandatory benchmark comparison, operational metrics and binding promotion gates. |
| `2026.07-execution-research-v3` | 2026-07-14 | Durable idempotency, startup reconciliation, hard risk/correlation limits, shared event-driven backtesting and truthful audit/coverage gates. |
| `2026.07-safety-foundation-v2` | 2026-07-14 | Mainnet compile lock, canonical execution request, atomic paper state and truthful CI policy. |
