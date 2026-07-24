# Phase 13 — Guarded Trading Execution and Strategy Validation

## Scope

Phase 13 strengthens the existing Testnet-only execution path and adds a
restart-safe Paper broker, mandatory simple strategy comparison and a combined
Paper/Testnet Shadow execution gate.

It does **not** enable Mainnet. `MAINNET_EXECUTION_COMPILED=False` remains the
build-time authority.

## Canonical exchange-write path

```text
TradingCandidate
  -> CandidateValidation(ALLOW)
  -> build_execution_request(...)
  -> ApprovedExecutionRequest
  -> BybitExecutionClient.execute(request)
  -> durable reservation
  -> Submitted
  -> Bybit Testnet /v5/order/create
  -> private order + execution evidence
  -> reconciliation
```

The adapter accepts only an `ApprovedExecutionRequest`. The removed
`place_market_order` method continues to fail. `_send_market_order` requires a
module-private capability object generated only inside `execute()`.

## Persistent kill switch

`EXECUTION_KILL_SWITCH=1` is the outer lock. The new persistent latch is stored
in `ProjectDatabase` and is tripped on:

- ambiguous network or provider outcome;
- accepted response without an `orderId`;
- unresolved durable execution state before a new submission;
- startup reconciliation failure.

The latch survives restart. Clearing requires:

```text
EXECUTION_KILL_SWITCH=0
restart_safe=true
unresolved_execution_count=0
confirmation=I_ACKNOWLEDGE_RECONCILIATION_IS_CLEAN
```

Restart, deployment, strategy output, SaaS subscription and dashboard actions
cannot clear it.

## Restart-safe Paper broker

`trading_core.paper_broker.RestartSafePaperBroker` persists:

- cash and equity inputs;
- open quantities and average entry prices;
- maker/taker fees;
- spread cost;
- deterministic slippage and nonlinear impact;
- funding accrual;
- realized PnL;
- bounded fill and funding evidence.

Each `fill_id` is idempotent. Exact replay returns the existing fill and does not
change cash or positions. Optimistic versions prevent concurrent lost updates.
Invalid state, negative cash, overselling and non-finite input fail closed.

## Strategy suite

The mandatory research set is:

1. Buy-and-Hold benchmark;
2. Trend Following;
3. Breakout;
4. Mean Reversion.

`evaluate_strategy_suite()` runs all four over the same immutable events and the
same `BacktestConfig`. The result exposes return, net PnL, maximum drawdown,
fees, slippage, funding, Sharpe, Sortino, profit factor, trade count and exposure
time.

A candidate fails Paper review when it:

- does not beat Buy-and-Hold after costs;
- has non-positive net PnL;
- has insufficient trades;
- exceeds the drawdown gate;
- produces invalid cost accounting.

A ranking never changes an experiment stage and never creates execution
authority.

## Shadow validation

`ShadowExecutionValidator` combines the existing fill-divergence analyzer with
execution-state integrity.

Required evidence:

- 20 or more matched Paper/Testnet fills;
- zero unmatched Paper/Testnet fills;
- bounded p95 latency and slippage divergence;
- bounded fee delta;
- bounded partial-fill rate and fill-ratio delta;
- zero unresolved execution reservations;
- restart-safe idempotency state;
- inactive persistent kill switch.

The resulting report is persisted with a SHA-256 evidence digest. It can set
`shadow_eligible=true`; it always sets `controlled_live_eligible=false`.

## Testnet operating sequence

1. Run complete CI on the exact SHA.
2. Deploy with Mainnet compiled out and the environment kill switch engaged.
3. Verify database, private streams and startup reconciliation.
4. Open a finite Testnet window through the existing operator workflow.
5. Clear the persistent latch only after a clean reconciliation report.
6. Start one bounded campaign with 10–25 USDT accepted notional per order.
7. Collect actual private fills and fees.
8. Run Shadow validation.
9. Generate immutable final report.
10. Make a separate manual Testnet decision.

## Controlled Mainnet is a later audited build

Before a separate build may change the compile lock, the Constitution requires
at least three distinct clean Testnet campaigns, 100 matched fills, zero identity
failures, clean crash drills, a limited no-withdrawal subaccount, legal review,
expiring SHA/account/scope-bound owner authorization and one-order-at-a-time
manual execution. Phase 13 does not satisfy or bypass that future gate.

## Verification commands

```bash
python -m pytest \
  tests/test_execution_contract.py \
  tests/test_execution_idempotency.py \
  tests/test_startup_reconciliation.py \
  tests/test_market_paper_engine.py \
  tests/test_trading_core_backtest.py \
  tests/test_trading_core_funding_walk_forward.py \
  tests/test_benchmark_strategies.py \
  tests/test_fill_divergence_validation.py \
  tests/test_phase13_execution_paper_shadow.py \
  -q --tb=short
```

Then run the full suite:

```bash
python -m pytest -q --tb=short
```
