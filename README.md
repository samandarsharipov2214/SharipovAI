# SharipovAI OS

SharipovAI is a safety-first AI trading operating system built around verified
market evidence, deterministic risk controls, persistent experiments, realistic
paper trading, walk-forward research and guarded exchange integration.

> **Current safety state:** Mainnet execution is compiled out. Testnet is disabled
> by default and requires `ApprovedExecutionRequest`, durable idempotency, fresh
> private-order WebSocket evidence and successful startup reconciliation.

SharipovAI does not guarantee profit. It measures whether a strategy has positive
expectancy after spread, maker/taker fees, slippage, nonlinear market impact,
funding, drawdown and execution failure modes.

Binding policy: [`CONSTITUTION.md`](CONSTITUTION.md).

## Canonical architecture

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

`ai_architecture_registry.py` is the ownership source of truth. Storage,
validation, experiment registries, monitoring, transport, idempotency and
backtesting are infrastructure, not extra AI organs.

## Safety invariants

- `MAINNET_EXECUTION_COMPILED=False` cannot be overridden by environment variables.
- `EXECUTION_KILL_SWITCH=1` is the safe default.
- Dashboard, Telegram, strategies, agents and LLM output cannot submit raw orders.
- Exchange writes use `BybitExecutionClient.execute(ApprovedExecutionRequest)`.
- Every request has a deterministic `sai_...` `orderLinkId` and durable reservation.
- Duplicate and ambiguous execution intents block retries.
- Testnet startup requires reconciliation and private-order stream evidence.
- Paper state is atomic, revisioned and recoverable.
- Experiment promotion never changes runtime execution flags.
- Backtests and manual approvals cannot enable Mainnet.
- Secrets and runtime state stay outside Git, logs, metrics and experiment payloads.

## Main components

| Component | Responsibility |
| --- | --- |
| `dashboard/` | FastAPI dashboard, auth dependencies and read-only operational routers |
| `dashboard/routers/execution_status.py` | Execution, risk, exposure and paper-PnL status |
| `dashboard/routers/experiments.py` | Backtest results, experiment comparison and promotion reports |
| `dashboard/routers/metrics.py` | Protected Prometheus text endpoint |
| `trading_candidate.py` | Fail-closed analytical candidate contract |
| `exchange_connector/execution_contract.py` | Immutable approved execution envelope |
| `exchange_connector/execution_idempotency.py` | Durable duplicate/unresolved protection |
| `exchange_connector/bybit_order_state.py` | Private order and partial-fill state |
| `exchange_connector/bybit_private_order_ws.py` | Read-only authenticated order stream |
| `exchange_connector/private_ws_gate.py` | Persistent stream readiness/heartbeat gate |
| `autonomous_trading/startup_reconciliation.py` | Identity, journal, private-state and stream reconciliation |
| `autonomous_trading/testnet_bridge.py` | Fresh canonical paper-candidate to Testnet mirror |
| `capital_allocation.py` | Reserve, risk, symbol and correlation allocation |
| `risk_engine/` | Hard limits and bounded soft-risk size scaling |
| `trading_core/` | Event-driven backtest, funding, walk-forward and benchmarks |
| `historical_data/` | Versioned manifests, Parquet validation and DuckDB loading |
| `experiments/` | Persistent experiment identity and promotion gate reports |
| `validation/` | Paper/Testnet fill divergence and validation persistence |
| `observability/` | Structured JSON logging and Prometheus-ready metrics |
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
  -> Private order WebSocket state
  -> Reconciliation
  -> Outcome and Learning Evidence
```

A timeout after submission remains unresolved. It is never treated as an automatic
retry signal.

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

Hard blocks include stale data, kill switch, invalid instruments, drawdown/loss
limits, exposure limits, liquidity floor, unresolved identity and unhealthy
private execution evidence. Soft risk only reduces size.

## Event-driven research

`trading_core.EventDrivenBacktester` processes immutable events in strict
`(timestamp_ms, symbol)` order and models:

- bid/ask spread;
- maker and taker fees;
- deterministic slippage;
- nonlinear participation impact;
- funding;
- reserve, symbol and correlation limits;
- mark-to-market equity, drawdown, Sharpe, Sortino and profit factor;
- no future lookup or synthetic fill.

`WalkForwardBacktester` supports sequential rolling and anchored out-of-sample
windows. Every candidate must be compared on identical data and costs against:

- buy-and-hold;
- trend following;
- breakout;
- mean reversion.

## Historical data

`historical_data` validates versioned manifests before creating `MarketEvent`
objects. It checks provenance, schema, symbol/time ranges, row count, hashes,
duplicates, price integrity and gaps, then queries Parquet through DuckDB.

```bash
python scripts/validate_historical_data.py data/history/manifest.json
```

Missing intervals remain visible. The loader never fabricates bars or trades.

## Persistent Experiment Registry

`ExperimentRegistry` stores each research run in `ProjectDatabase` with:

- experiment ID;
- source commit SHA;
- manifest ID/version/hash and validation state;
- strategy and backtest configuration;
- walk-forward results;
- benchmark table;
- data-quality result;
- paper summary;
- Paper/Testnet fill validation;
- automated promotion report;
- manual approval or rejection.

Example:

```python
from dataclasses import asdict
from experiments import ExperimentRegistry, PromotionGateEngine

registry = ExperimentRegistry()
experiment = registry.create(
    commit_sha="<git-commit-sha>",
    manifest={
        "manifest_id": "bybit-btc-linear-1m",
        "version": "2026-07-v1",
        "sha256": "<optional-64-char-hash>",
        "validated": True,
    },
    strategy_name="trend_candidate_v1",
    strategy_config={"fast": 20, "slow": 100},
    backtest_config={"fee_rate": 0.001, "slippage_bps": 2.0},
)

experiment = registry.record_result(
    experiment["experiment_id"],
    "walk_forward",
    asdict(walk_forward_result),
    actor="research-runner",
    expected_version=experiment["version"],
)
```

The registry uses optimistic versions and append-only events. It cannot modify
execution settings.

## Paper/Testnet fill validation

`FillDivergenceAnalyzer` matches stable execution identities and compares:

- first-fill latency;
- signed slippage in basis points;
- requested versus filled quantity;
- partial-fill rate;
- fee divergence;
- unmatched Paper or Testnet fills.

```python
from validation import FillDivergenceAnalyzer, FillValidationRepository

report = FillDivergenceAnalyzer().analyze(paper_fills, testnet_fills)
FillValidationRepository().save(
    report,
    experiment_id="exp_...",
    actor="general-controller",
)
```

Default promotion tolerances require at least 20 matched pairs, no unmatched fills,
p95 latency divergence <= 2000 ms, p95 slippage divergence <= 15 bps, partial-fill
rate <= 20% and maximum fill-ratio delta <= 0.10.

## Private WebSocket startup gate

The private Bybit worker is read-only and subscribes only to the `order` topic.
When Testnet execution is requested, startup requires persisted evidence that the
worker is running, connected, authenticated, subscribed and has a fresh heartbeat.

Safe default:

```env
FEATURE_BYBIT_PRIVATE_ORDER_WS=0
TESTNET_EXECUTION_ENABLED=0
AUTONOMOUS_TESTNET_ENABLED=0
AUTONOMOUS_TESTNET_BRIDGE_ENABLED=0
```

Enabling Testnet without the private stream produces a blocking reconciliation
report; it does not fall back to REST-only execution.

## Promotion Gate Engine

Promotion stages:

```text
READ_ONLY -> PAPER -> TESTNET -> CONTROLLED_MAINNET -> SCALE
```

`PromotionGateEngine` creates a report. It does not perform promotion itself.

Research -> PAPER requires validated data, six or more OOS windows, at least 60%
profitable windows, positive all-cost OOS PnL, controlled drawdown, positive
risk-adjusted score and mandatory benchmark performance.

PAPER -> TESTNET additionally requires sustained paper evidence, fill divergence
within policy, zero unresolved intents, fresh private stream evidence, startup
reconciliation and manual approval.

TESTNET -> CONTROLLED_MAINNET remains blocked while Mainnet is compiled out.

Manual approval token format:

```text
APPROVE:<experiment_id>:<target_stage>
```

A failed automated gate cannot be manually overridden. A successful approval does
not change Testnet/Mainnet flags, credentials, capital or deployment.

## Dashboard routes

Start locally:

```bash
uvicorn dashboard:app --reload
```

| Route | Purpose |
| --- | --- |
| `/execution-status` | Read-only execution, risk, exposure and Paper PnL |
| `/backtest-results` | Persistent experiment and promotion status |
| `/experiment-comparison?ids=exp-a,exp-b` | Side-by-side OOS comparison |
| `/api/experiments` | Experiment registry JSON |
| `/api/experiments/compare?ids=exp-a,exp-b` | Comparison JSON |
| `/api/experiments/{id}` | Experiment, history and fill validations |
| `/metrics` | Protected Prometheus text endpoint |
| `/virtual-account` | Paper account and trade history |

Promotion-report and decision endpoints require administrator authentication.
They never expose a raw order primitive.

## Safe environment defaults

```env
EXCHANGE_MODE=sandbox
EXCHANGE_BASE_URL=https://api-testnet.bybit.com
EXCHANGE_LIVE_TRADING_ENABLED=0
LIVE_EXECUTION_MANUAL_UNLOCK=0
TESTNET_EXECUTION_ENABLED=0
AUTONOMOUS_TESTNET_ENABLED=0
AUTONOMOUS_TESTNET_BRIDGE_ENABLED=0
FEATURE_BYBIT_PRIVATE_ORDER_WS=0
EXECUTION_KILL_SWITCH=1
EXECUTION_MAX_NOTIONAL_USDT=25
BYBIT_PRIVATE_WS_GATE_MAX_AGE_SECONDS=60

VIRTUAL_ACCOUNT_RESERVE_PERCENT=20
VIRTUAL_ACCOUNT_MAX_TOTAL_EXPOSURE_PERCENT=80
VIRTUAL_ACCOUNT_MAX_POSITION_PERCENT=20
VIRTUAL_ACCOUNT_MAX_SYMBOL_EXPOSURE_PERCENT=20
VIRTUAL_ACCOUNT_MAX_CORRELATED_EXPOSURE_PERCENT=35
VIRTUAL_ACCOUNT_MAX_RISK_PER_TRADE_PERCENT=1
VIRTUAL_ACCOUNT_MAX_DAILY_LOSS_PERCENT=2
```

These values do not enable exchange writes. Mainnet remains unavailable even if
every environment variable is changed.

## Development setup

Python 3.12 is required.

```bash
python -m venv .venv
source .venv/bin/activate  # Windows PowerShell: .venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements-dev.txt
```

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
  tests/test_private_ws_startup_gate.py \
  tests/test_experiment_registry_promotion.py \
  tests/test_fill_divergence_validation.py \
  tests/test_experiment_dashboard.py \
  tests/test_risk_hard_limits.py \
  tests/test_trading_core_funding_walk_forward.py \
  tests/test_benchmark_strategies.py \
  tests/test_historical_data_layer.py \
  -q --tb=short

python -m pytest -q --tb=short
```

CI keeps dependency-audit, coverage, JUnit, complete pytest logs and compact failure
reports. A partial or skipped suite is not a green release.

## Development workflow

1. Work in a branch and keep the PR draft until factual checks pass.
2. Keep Testnet/Mainnet disabled by default.
3. Record every research run in the Experiment Registry.
4. Validate every historical manifest.
5. Compare every candidate with all mandatory benchmarks.
6. Validate Paper/Testnet execution divergence before Testnet promotion.
7. Require private WebSocket health and startup reconciliation.
8. Persist automated reports and separate manual decisions.
9. Resolve every ambiguous execution before retry.
10. Merge only after complete green CI and a documented rollback.

## Security

- Rotate any token or key exposed in chat, screenshots or logs.
- Separate read-only, Testnet and future Mainnet credentials.
- Disable withdrawals and transfers for automated keys.
- Keep production secrets outside Git, logs, metrics, experiments and Evidence.
- Treat unexpected account, position, stream or order state as a kill-switch event.
