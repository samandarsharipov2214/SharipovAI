# SharipovAI Constitution

Version: `2026.07-execution-research-v3`  
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

Only capital and fills are virtual. Quotes, timestamps, fees, bid/ask spread,
slippage, funding, risk, drawdown and Evidence must be treated as production
inputs.

Paper state must be durable, atomic, revisioned and recoverable from a
last-known-good backup. Synthetic historical prices, fabricated trades and fake
catch-up fills are forbidden.

A paper trade may reach Testnet only when it references a stored canonical
`TradingCandidate`, is recent enough for mirroring, matches symbol/side/price and
passes fresh validation again.

## 7. Backtesting integrity

1. Backtests process immutable events in chronological order.
2. Lookahead, future leakage and random time-series train/test splits are
   forbidden.
3. Results include bid/ask spread, fees and slippage; funding and latency must be
   added before derivatives/live promotion.
4. Backtest, paper and Testnet must converge on shared domain models, cost logic,
   risk limits and capital allocation.
5. Every run records strategy/config version, data provenance and commit SHA.
6. Promotion requires out-of-sample and walk-forward evidence, not one profitable
   in-sample chart.
7. A backtest is research evidence, never permission to enable Mainnet.

## 8. Canonical architecture

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

## 9. Learning and strategy changes

Learning may create lessons, proposals and challenger strategies. It may not:

- edit or deploy production trading rules automatically;
- enable exchange writes;
- increase capital or leverage;
- remove Risk/Security vetoes;
- reinterpret an unresolved order as failed and retry it;
- treat confidence as proof of profitability.

Promotion requires reproducible tests, out-of-sample evidence, champion/challenger
comparison and General Controller approval.

## 10. Database and Evidence

`ProjectDatabase` is the canonical source of truth for execution intents, order
state, audit, learning and project memory. JSON files are bounded backups/caches,
not execution authority.

Secrets, seed phrases, private keys, API secrets and credentials are forbidden in
Git, logs, Evidence, change ledgers, test artifacts and prompts.

## 11. CI and merge rules

A change is mergeable only when all relevant factual gates complete:

- dependency installation and `pip check`;
- `pip-audit` without unapproved vulnerabilities;
- Python compilation;
- critical imports;
- hard Mainnet-lock verification;
- execution/idempotency/reconciliation tests;
- risk/capital/backtesting safety tests;
- critical-module coverage threshold;
- complete pytest suite;
- test and coverage artifacts retained;
- no secret/runtime-state commit;
- explicit rollback path.

A static score, partial suite or AI statement cannot override a failed or skipped
full suite. Testnet and Mainnet remain disabled by default in CI.

## 12. Profit and user claims

SharipovAI reports measured results after all modeled costs. It must not promise
guaranteed income, fabricate performance or scale capital based only on a
backtest, confidence score or narrative.

## Change history

| Version | Date | Summary |
| --- | --- | --- |
| `2026.07-execution-research-v3` | 2026-07-14 | Durable idempotency, startup reconciliation, hard risk/correlation limits, shared event-driven backtesting and truthful audit/coverage gates. |
| `2026.07-safety-foundation-v2` | 2026-07-14 | Mainnet compile lock, canonical execution request, atomic paper state and truthful CI policy. |
