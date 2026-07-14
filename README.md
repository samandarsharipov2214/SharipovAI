# SharipovAI OS

SharipovAI is a safety-first AI trading operating system built around verified
market evidence, deterministic risk controls, persistent paper trading,
event-driven strategy research and guarded exchange integration.

> **Current safety state:** Mainnet execution is compiled out. Testnet is disabled
> by default and can write only through a short-lived `ApprovedExecutionRequest`
> with a durable idempotency reservation. An unresolved execution blocks restart.

SharipovAI does not guarantee profit. Its job is to measure whether a strategy has
positive expectancy after spread, maker/taker fees, slippage, nonlinear market
impact, funding, drawdown and execution failure modes.

Binding policy: [`CONSTITUTION.md`](CONSTITUTION.md).

## Architecture

The canonical architecture has nine AI organs:

1. General Controller
2. Market Intelligence
3. News Intelligence
4. Risk Engine
5. Portfolio Engine
6. Virtual Execution
7. Decision Quality
8. Learning Engine
9. Security Guard

`ai_architecture_registry.py` is the ownership source of truth. Infrastructure
such as storage, execution idempotency, historical data, observability and
backtesting does not become another AI organ.

## Safety invariants

- `MAINNET_EXECUTION_COMPILED=False` cannot be overridden by environment variables.
- `EXECUTION_KILL_SWITCH=1` is the safe default.
- Dashboard, Telegram, agents, strategies and LLM output cannot create raw orders.
- The legacy `place_market_order()` entry point is removed.
- Exchange writes use `BybitExecutionClient.execute(ApprovedExecutionRequest)`.
- Every request has a deterministic `sai_...` `orderLinkId` and is reserved in
  `ProjectDatabase` before the HTTP call.
- Duplicate and unresolved intents are blocked; transport timeouts are reconciled,
  never retried blindly.
- Startup compares idempotency reservations, execution journal and private Bybit
  order state before Testnet may continue.
- Paper state is atomic, revisioned and recoverable.
- Backtests cannot enable Testnet or Mainnet.
- Secrets, account snapshots, runtime databases and execution journals stay out of Git.

## Main components

| Component | Responsibility |
| --- | --- |
| `dashboard/` | FastAPI dashboard, separated operational routers and auth dependencies |
| `dashboard/routers/execution_status.py` | Read-only execution, risk, exposure and paper-PnL status |
| `dashboard/routers/metrics.py` | Prometheus text endpoint with token/admin access |
| `trading_candidate.py` | Fail-closed analytical candidate contract |
| `exchange_connector/execution_contract.py` | Immutable approved execution envelope |
| `exchange_connector/execution_idempotency.py` | Durable duplicate/unresolved protection |
| `exchange_connector/bybit_order_identity.py` | Canonical deterministic order identity registry |
| `exchange_connector/bybit_order_state.py` | Private order lifecycle and partial-fill state |
| `autonomous_trading/startup_reconciliation.py` | Restart reconciliation and fail-closed gate |
| `autonomous_trading/testnet_bridge.py` | Fresh paper-candidate to Testnet mirror |
| `capital_allocation.py` | Reserve, risk, symbol and correlation exposure allocation |
| `risk_engine/` | Hard limits, soft score and position-size multiplier |
| `trading_core/` | Event-driven backtest, funding, walk-forward and benchmarks |
| `historical_data/` | Versioned manifests, Parquet validation and DuckDB loading |
| `observability/` | Structured JSON logging and Prometheus-ready metrics |
| `paper_activity_engine.py` | Durable virtual-account state |
| `storage/` | Canonical shared database and Evidence ledger |

## Canonical execution path

```text
Verified market evidence
  -> Portfolio snapshot
  -> Risk Engine hard limits
  -> Capital allocation
  -> Decision Quality
  -> Security Guard
  -> TradingCandidate validation
  -> ApprovedExecutionRequest
  -> Idempotency reservation
  -> Bybit Testnet submission
  -> Private order state
  -> Reconciliation
  -> Outcome/Learning Evidence
```

```python
validation = validate_trading_candidate(candidate, now_ms=now_ms)
request = build_execution_request(
    candidate,
    validation,
    quantity=quantity,
    now_ms=now_ms,
)
result = BybitExecutionClient(database=database).execute(
    request,
    now_ms=now_ms,
)
```

A timeout after submission leaves the request unresolved. The same request cannot
be sent again until reconciliation resolves its state.

## Risk and capital defaults

| Rule | Default |
| --- | ---: |
| Reserve | 20% |
| Maximum total exposure | 80% |
| Maximum one position | 20% |
| Maximum one symbol | 20% |
| Maximum correlated group | 35% |
| Maximum risk per trade | 1% |
| Daily loss stop | 2% |
| Portfolio drawdown stop | 10% |
| Leverage | 1× |

Hard blocks include stale data, active kill switch, invalid instruments,
drawdown/loss limits, exposure limits, liquidity floor and maximum positions.
Soft risk only scales size: `LOW=100%`, `MEDIUM=60%`, `HIGH=25%`,
`CRITICAL=0%`.

## Event-driven backtesting

`trading_core.EventDrivenBacktester` processes immutable events in strict
`(timestamp_ms, symbol)` order. It includes:

- explicit bid and ask spread;
- maker and taker fees;
- deterministic base slippage;
- nonlinear impact based on order participation;
- a hard maximum participation rate;
- proportional funding accrual for open derivative positions;
- shared reserve, position, symbol and correlation limits;
- mark-to-market equity, drawdown, Sharpe, Sortino and profit factor;
- no future lookup or synthetic fills.

```python
from trading_core import (
    BacktestConfig,
    EventDrivenBacktester,
    MarketEvent,
    Side,
    Signal,
)


class Strategy:
    def on_market(self, event, portfolio):
        if event.symbol not in portfolio.positions:
            return Signal(
                Side.BUY,
                requested_risk_percent=1.0,
                stop_loss_percent=1.0,
                liquidity_role="taker",
                reason="entry",
            )
        return None


events = [
    MarketEvent(
        timestamp_ms=1,
        symbol="BTCUSDT",
        bid=99.9,
        ask=100.0,
        volume=1_000_000.0,
        funding_rate=0.0001,
        funding_interval_hours=8.0,
    )
]
result = EventDrivenBacktester(BacktestConfig()).run(events, Strategy())
print(result.net_pnl, result.total_funding_cost, result.max_drawdown_percent)
```

## Walk-forward evaluation

`trading_core.WalkForwardBacktester` exposes each strategy factory only to the
past training slice and evaluates the next sequential out-of-sample slice.
Rolling and anchored training windows are supported.

```python
from trading_core import (
    BacktestConfig,
    BuyAndHoldStrategy,
    WalkForwardBacktester,
    WalkForwardConfig,
)

runner = WalkForwardBacktester(
    BacktestConfig(),
    WalkForwardConfig(
        train_events=2_000,
        test_events=500,
        step_events=500,
        minimum_windows=6,
        anchored=False,
        chain_capital=True,
    ),
)

result = runner.run(
    events,
    lambda train_events, window_index: BuyAndHoldStrategy(),
)
print(result.profitable_window_percent, result.return_percent)
```

Promotion rules require multiple profitable out-of-sample windows and do not
permit one favorable in-sample chart to advance a strategy.

## Mandatory benchmark strategies

Every candidate must be compared on the same event set and identical costs with:

- buy-and-hold;
- moving-average trend following;
- rolling breakout;
- mean reversion.

```python
from trading_core import compare_strategy_to_benchmarks

comparison = compare_strategy_to_benchmarks(
    events,
    strategy_factory=lambda: Strategy(),
    candidate_name="candidate_v1",
)
print(comparison.ranking)
print(comparison.metadata["candidate_beats_buy_hold"])
```

The comparison includes spread, fees, slippage, market impact and funding. A
candidate cannot omit an unfavorable benchmark.

## Historical data layer

`historical_data` uses DuckDB to query Parquet directly. Data is rejected before
replay when the manifest, schema, ranges, symbols, hashes, prices or duplicate
checks fail.

Example `manifest.json`:

```json
{
  "schema_version": 1,
  "dataset_id": "bybit-btc-linear-1m",
  "dataset_version": "2026-07-v1",
  "venue": "bybit",
  "market_type": "linear",
  "source": "verified-export",
  "symbols": ["BTCUSDT"],
  "interval_ms": 60000,
  "timezone": "UTC",
  "start_timestamp_ms": 1735689600000,
  "end_timestamp_ms": 1767225540000,
  "row_count": 525600,
  "parquet_files": ["btc-usdt-1m.parquet"],
  "required_columns": ["timestamp_ms", "symbol"],
  "optional_columns": ["bid", "ask", "close", "volume", "funding_rate"],
  "default_spread_bps": 2.0,
  "funding_included": true,
  "sha256": {}
}
```

Validate from CLI:

```bash
python scripts/validate_historical_data.py data/history/manifest.json
```

Load canonical events:

```python
from historical_data import HistoricalDataLoader

with HistoricalDataLoader("data/history/manifest.json") as loader:
    events = tuple(
        loader.iter_events(
            symbols=["BTCUSDT"],
            start_timestamp_ms=1735689600000,
        )
    )
```

When only `close` exists, bid and ask are derived from the manifest spread. The
loader never fabricates missing timestamps or trades.

## Dashboard and operational views

Start locally:

```bash
uvicorn dashboard:app --reload
```

Operational routes:

| Route | Purpose |
| --- | --- |
| `/execution-status` | Admin read-only execution, risk, exposure and paper-PnL page |
| `/api/execution/status` | Same state as JSON |
| `/api/execution/stage-status` | Existing stage and execution evidence |
| `/metrics` | Prometheus text format; bearer token or admin authentication |
| `/virtual-account` | Paper account and trade history |

The execution page does not submit orders. It reports the actual execution lock,
kill switch, stage, journal, reserve, exposure, paper equity and net PnL.

For Prometheus scraping in production:

```env
SHARIPOVAI_METRICS_TOKEN=generate-a-long-random-token
```

```bash
curl -H "Authorization: Bearer $SHARIPOVAI_METRICS_TOKEN" \
  http://127.0.0.1:8000/metrics
```

Do not put user IDs, symbols with unbounded cardinality, candidate IDs or secrets
into Prometheus labels.

## Structured logging

`observability.structured_logging` emits one JSON object per record and redacts
credential-like keys.

```python
from observability import get_structured_logger, log_event
import logging

logger = get_structured_logger("sharipovai.research", component="walk_forward")
log_event(
    logger,
    logging.INFO,
    "walk_forward_completed",
    event="walk_forward_completed",
    window_index=3,
    context={"dataset_id": "bybit-btc-linear-1m"},
)
```

HTTP middleware adds request IDs, duration, status and path metrics. Observability
is read-only and must never change trading output.

## Local setup

Python 3.12 is required.

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
python -m pip install --upgrade pip
python -m pip install -r requirements-dev.txt
```

Never commit a populated `.env` or runtime Parquet data by accident.

## Safety and quality checks

```bash
python -m pip check
python -m pip_audit -r requirements.txt --progress-spinner off
python -m compileall -q .
python scripts/execution_foundation_audit.py
python scripts/research_foundation_audit.py --json

python -m pytest \
  tests/test_execution_contract.py \
  tests/test_execution_idempotency.py \
  tests/test_startup_reconciliation.py \
  tests/test_risk_hard_limits.py \
  tests/test_capital_allocation.py \
  tests/test_trading_core_backtest.py \
  tests/test_trading_core_funding_walk_forward.py \
  tests/test_benchmark_strategies.py \
  tests/test_historical_data_layer.py \
  tests/test_observability.py \
  tests/test_execution_status_router.py \
  -q --tb=short

python -m pytest -q --tb=short
```

CI records critical-module coverage, JUnit output, full pytest logs and a compact
failure report. A partial or skipped suite is not a green release.

## Safe environment defaults

```env
EXCHANGE_MODE=sandbox
EXCHANGE_BASE_URL=https://api-testnet.bybit.com
EXCHANGE_LIVE_TRADING_ENABLED=0
LIVE_EXECUTION_MANUAL_UNLOCK=0
AUTONOMOUS_TESTNET_BRIDGE_ENABLED=0
AUTONOMOUS_TESTNET_ENABLED=0
TESTNET_EXECUTION_ENABLED=0
EXECUTION_KILL_SWITCH=1
EXECUTION_MAX_NOTIONAL_USDT=25
TESTNET_MIRROR_MAX_TRADE_AGE_MS=5000

VIRTUAL_ACCOUNT_RESERVE_PERCENT=20
VIRTUAL_ACCOUNT_MAX_TOTAL_EXPOSURE_PERCENT=80
VIRTUAL_ACCOUNT_MAX_POSITION_PERCENT=20
VIRTUAL_ACCOUNT_MAX_SYMBOL_EXPOSURE_PERCENT=20
VIRTUAL_ACCOUNT_MAX_CORRELATED_EXPOSURE_PERCENT=35
VIRTUAL_ACCOUNT_MAX_RISK_PER_TRADE_PERCENT=1
VIRTUAL_ACCOUNT_MAX_DAILY_LOSS_PERCENT=2
```

These settings do not enable exchange writes. Testnet additionally requires
isolated Testnet credentials and completed safety/stage gates. Mainnet remains
unavailable even if every environment flag is changed.

## Development workflow

1. Work in a branch and keep PRs draft until factual checks pass.
2. Keep Testnet/Mainnet disabled by default.
3. Add tests for every execution, risk, persistence, data and strategy change.
4. Validate every historical manifest before research.
5. Compare every candidate with all mandatory benchmarks.
6. Run dependency audit, research audits, critical coverage and complete pytest.
7. Review the diff for secrets, runtime data and safety-flag changes.
8. Resolve every ambiguous execution through reconciliation.
9. Merge only after factual green checks and a documented rollback.

## Security

- Rotate any token or key exposed in chat, screenshots or logs.
- Separate read-only, Testnet and future Mainnet credentials.
- Disable withdrawals and transfers for automated keys.
- Keep production secrets outside Git, logs, metrics and Evidence payloads.
- Treat unexpected account, position or order state as a kill-switch event.
