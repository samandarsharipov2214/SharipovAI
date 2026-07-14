# SharipovAI OS

SharipovAI is a safety-first AI trading operating system built around verified
market evidence, deterministic risk controls, persistent experiments, realistic
paper trading, walk-forward research and guarded exchange integration.

> **Current safety state:** Mainnet execution is compiled out. Testnet is disabled
> by default and requires `ApprovedExecutionRequest`, durable idempotency, fresh
> private-order WebSocket evidence, actual Bybit instrument rules and successful
> startup reconciliation.

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
validation, experiment registries, monitoring, transport, idempotency, automatic
experiments and backtesting are infrastructure, not extra AI organs.

## Safety invariants

- `MAINNET_EXECUTION_COMPILED=False` cannot be overridden by environment variables.
- `EXECUTION_KILL_SWITCH=1` is the safe default.
- Dashboard, Telegram, strategies, agents and LLM output cannot submit raw orders.
- Exchange writes use `BybitExecutionClient.execute(ApprovedExecutionRequest)`.
- Every request has a deterministic `sai_...` `orderLinkId` and durable reservation.
- Duplicate and ambiguous execution intents block retries.
- Testnet startup requires reconciliation and private-order stream evidence.
- Shadow Testnet notional is hard-capped at 25 USDT in this build.
- Paper sizing is not changed by Testnet shadow mode.
- Experiment and champion promotion never changes runtime execution flags.
- Backtests and manual approvals cannot enable Mainnet.
- Secrets and runtime state stay outside Git, logs, metrics and experiment payloads.

## Main components

| Component | Responsibility |
| --- | --- |
| `dashboard/` | FastAPI dashboard, auth dependencies and read-only operational routers |
| `dashboard/routers/execution_status.py` | Execution, risk, exposure and paper-PnL status |
| `dashboard/routers/experiments.py` | Backtest results, experiment comparison and promotion reports |
| `dashboard/fill_harvester_api.py` | Admin status/manual trigger for runtime fill validation |
| `dashboard/routers/metrics.py` | Protected Prometheus text endpoint |
| `trading_candidate.py` | Fail-closed analytical candidate contract |
| `exchange_connector/execution_contract.py` | Immutable approved execution envelope |
| `exchange_connector/execution_idempotency.py` | Durable duplicate/unresolved protection |
| `exchange_connector/bybit_reference_data.py` | Actual fee tier and instrument filters |
| `exchange_connector/bybit_order_state.py` | Private order and partial-fill state |
| `exchange_connector/bybit_private_order_ws.py` | Read-only authenticated order stream |
| `exchange_connector/private_ws_gate.py` | Persistent stream readiness/heartbeat gate |
| `autonomous_trading/shadow_mode.py` | Bounded Paper/Testnet shadow order planning |
| `autonomous_trading/shadow_bridge.py` | Canonical shadow-only Testnet bridge |
| `autonomous_trading/startup_reconciliation.py` | Identity, journal, private-state and stream reconciliation |
| `capital_allocation.py` | Reserve, risk, symbol and correlation allocation |
| `risk_engine/` | Hard limits and bounded soft-risk size scaling |
| `trading_core/` | Event-driven backtest, funding, walk-forward and benchmarks |
| `historical_data/` | Versioned manifests, Parquet validation and DuckDB loading |
| `experiments/registry.py` | Persistent experiment identity and promotion evidence |
| `experiments/runner.py` | Automatic immutable walk-forward/benchmark runner |
| `experiments/champion_challenger.py` | Evidence-gated strategy leadership |
| `validation/fill_divergence.py` | Paper/Testnet divergence analysis |
| `validation/runtime_fill_harvester.py` | Automatic runtime fill evidence collection |
| `observability/` | Structured JSON logging and Prometheus-ready metrics |
| `storage/` | Canonical shared database and Evidence ledger |

## Canonical execution and evidence path

```text
Verified market evidence
  -> Portfolio snapshot
  -> Risk Engine hard limits
  -> Capital allocation
  -> Decision Quality
  -> Security Guard
  -> TradingCandidate validation
  -> Paper execution
  -> ShadowModePlanner
  -> actual Bybit fee/instrument snapshot
  -> ApprovedExecutionRequest
  -> idempotency reservation
  -> Bybit Testnet submission
  -> private order WebSocket state
  -> RuntimeFillHarvester
  -> FillDivergenceAnalyzer
  -> promotion evidence
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
`(timestamp_ms, symbol)` order and models bid/ask spread, maker/taker fees,
slippage, nonlinear participation impact, funding, risk allocation and drawdown.

`WalkForwardBacktester` supports sequential rolling and anchored out-of-sample
windows. Every candidate is compared on identical data and costs with:

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

## Automatic Experiment Runner

`AutomaticExperimentRunner` creates a deterministic experiment from:

- source commit SHA;
- validated `DataManifest` identity;
- strategy configuration;
- `BacktestConfig`;
- `WalkForwardConfig`.

It runs data validation, walk-forward evaluation and mandatory benchmarks, then
stores every result in the write-once
`research_experiment_immutable_results` namespace. The SHA-256 of each immutable
result is referenced by `ExperimentRegistry`.

```python
from experiments import AutomaticExperimentRequest, AutomaticExperimentRunner
from trading_core import BacktestConfig, BuyAndHoldStrategy, WalkForwardConfig

request = AutomaticExperimentRequest(
    commit_sha="<commit-sha>",
    strategy_name="candidate_v1",
    strategy_config={"lookback": 50},
    backtest_config=BacktestConfig(),
    walk_forward_config=WalkForwardConfig(
        train_events=2_000,
        test_events=500,
        step_events=500,
        minimum_windows=6,
    ),
    manifest_path="data/history/manifest.json",
)

experiment = AutomaticExperimentRunner().run(
    request,
    walk_forward_strategy_factory=lambda train, index: BuyAndHoldStrategy(),
    benchmark_strategy_factory=lambda: BuyAndHoldStrategy(),
)
```

A duplicate commit/manifest/config fingerprint is rejected instead of overwriting
prior evidence.

## Persistent Experiment Registry

`ExperimentRegistry` stores experiment ID, commit SHA, manifest identity,
configuration, walk-forward results, benchmark table, data quality, fill validation,
automated promotion report and manual decision in `ProjectDatabase`.

The registry uses optimistic versions and append-only events. It cannot modify
execution settings.

## Actual Bybit trading costs and filters

`BybitTradingReferenceClient` is read-only. For each symbol/category it fetches:

- actual account maker/taker rates from `/v5/account/fee-rate`;
- `tickSize`, `qtyStep`, minimum quantity, minimum notional and maximum market
  quantity from `/v5/market/instruments-info`.

Snapshots are validated, timestamped, cached in `ProjectDatabase` and expire.
Shadow execution fails closed when the snapshot is missing or stale. Quantity is
rounded down to `qtyStep`; it is never rounded up to force an order through.

Static fee tables remain educational only and are not execution authority.

## Testnet Shadow Mode

`ShadowModeTestnetBridge` is the canonical compatibility implementation behind
`AutonomousTestnetBridge`.

It preserves one source candidate for Paper and Testnet evidence while keeping the
executions separate:

- Paper quantity and accounting remain unchanged;
- Testnet receives a fresh canonical candidate;
- source candidate, Testnet candidate and `shadow_pair_id` are persisted;
- Testnet quantity is normalized with actual Bybit filters;
- notional is capped at the lower of policy and 25 USDT;
- instrument/fee evidence is stored in the bridge record and execution journal;
- private WebSocket and reconciliation remain mandatory.

Safe defaults:

```env
AUTONOMOUS_TESTNET_BRIDGE_ENABLED=0
AUTONOMOUS_TESTNET_ENABLED=0
TESTNET_EXECUTION_ENABLED=0
SHADOW_TESTNET_MAX_NOTIONAL_USDT=25
SHADOW_MAX_TRADE_AGE_MS=5000
```

## Runtime Fill Harvester

`RuntimeFillHarvester` joins the canonical Paper trade, shadow bridge record,
`orderLinkId` and private Testnet order lifecycle. It automatically builds a
`FillDivergenceAnalyzer` report covering:

- first-fill latency;
- signed slippage in basis points;
- fee divergence;
- requested versus filled quantity;
- partial-fill rate;
- unmatched Paper/Testnet fills.

The worker is default-off:

```env
RUNTIME_FILL_HARVESTER_ENABLED=0
SHADOW_EXPERIMENT_ID=
FILL_HARVEST_INTERVAL_SECONDS=15
```

Admin endpoints:

```text
GET  /api/validation/fill-harvester/status
POST /api/validation/fill-harvester/run?experiment_id=<experiment-id>
```

The harvester is read-only with respect to exchange execution.

## Champion–Challenger Registry

`ChampionChallengerRegistry` keeps exactly one champion per strategy scope and any
number of evidence-backed challengers.

A challenger must have completed research. A champion must additionally have:

- automated promotion report passed;
- no failed gates;
- manual experiment approval for the exact stage;
- scope-bound leadership token:

```text
PROMOTE:<scope>:<experiment_id>:<target_stage>
```

Leadership decisions store actor, reason, evidence SHA-256, previous champion and
timestamp. They do not deploy code or enable Testnet/Mainnet.

## Paper/Testnet fill validation

`FillDivergenceAnalyzer` and `FillValidationRepository` persist latency, slippage,
fees, fill ratio, partial-fill and unmatched-fill evidence.

Default promotion tolerances require at least 20 matched pairs, no unmatched fills,
p95 latency divergence <= 2000 ms, p95 slippage divergence <= 15 bps, partial-fill
rate <= 20% and maximum fill-ratio delta <= 0.10.

## Private WebSocket startup gate

The private Bybit worker is read-only and subscribes only to the `order` topic.
When Testnet is requested, startup requires persisted evidence that it is running,
connected, authenticated, subscribed and has a fresh heartbeat.

```env
FEATURE_BYBIT_PRIVATE_ORDER_WS=0
TESTNET_EXECUTION_ENABLED=0
AUTONOMOUS_TESTNET_ENABLED=0
AUTONOMOUS_TESTNET_BRIDGE_ENABLED=0
```

Enabling Testnet without the private stream produces a blocking reconciliation
report; it does not fall back to REST-only execution.

## Promotion Gate Engine

Stages:

```text
READ_ONLY -> PAPER -> TESTNET -> CONTROLLED_MAINNET -> SCALE
```

`PromotionGateEngine` creates a report only. It does not perform promotion itself.
A failed automated gate cannot be manually overridden. A successful approval does
not change Testnet/Mainnet flags, credentials, capital or deployment.

Manual experiment approval:

```text
APPROVE:<experiment_id>:<target_stage>
```

TESTNET -> CONTROLLED_MAINNET remains blocked while Mainnet is compiled out.

## Dashboard routes

```bash
uvicorn dashboard:app --reload
```

| Route | Purpose |
| --- | --- |
| `/execution-status` | Read-only execution, risk, exposure and Paper PnL |
| `/backtest-results` | Persistent experiment and promotion status |
| `/experiment-comparison?ids=exp-a,exp-b` | Side-by-side OOS comparison |
| `/api/experiments` | Experiment Registry JSON |
| `/api/experiments/compare?ids=exp-a,exp-b` | Comparison JSON |
| `/api/experiments/{id}` | Experiment, history and fill validations |
| `/api/validation/fill-harvester/status` | Runtime harvester status |
| `/metrics` | Protected Prometheus text endpoint |
| `/virtual-account` | Paper account and trade history |

Promotion and harvester write endpoints require administrator authentication.
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
RUNTIME_FILL_HARVESTER_ENABLED=0
EXECUTION_KILL_SWITCH=1
EXECUTION_MAX_NOTIONAL_USDT=25
SHADOW_TESTNET_MAX_NOTIONAL_USDT=25
BYBIT_REFERENCE_TTL_SECONDS=300
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
python scripts/promotion_foundation_audit.py --json
python scripts/campaign_foundation_audit.py --json

python -m pytest \
  tests/test_automatic_experiment_runner.py \
  tests/test_bybit_reference_data.py \
  tests/test_shadow_mode.py \
  tests/test_runtime_fill_harvester.py \
  tests/test_champion_challenger_registry.py \
  tests/test_execution_contract.py \
  tests/test_startup_reconciliation.py \
  tests/test_private_ws_startup_gate.py \
  tests/test_experiment_registry_promotion.py \
  tests/test_fill_divergence_validation.py \
  tests/test_risk_hard_limits.py \
  tests/test_trading_core_funding_walk_forward.py \
  tests/test_benchmark_strategies.py \
  tests/test_historical_data_layer.py \
  -q --tb=short

python -m pytest -q --tb=short
```

CI keeps dependency-audit, coverage, JUnit, complete pytest logs, all foundation
audits and compact failure reports. A partial or skipped suite is not a green release.

## Development workflow

1. Keep the PR draft until all factual checks pass.
2. Keep Testnet/Mainnet and the harvester disabled by default.
3. Record every research run in the Experiment Registry.
4. Use the Automatic Experiment Runner for reproducible campaigns.
5. Validate every historical manifest.
6. Compare every candidate with all mandatory benchmarks.
7. Validate actual Bybit filters before shadow submission.
8. Validate Paper/Testnet divergence before Testnet promotion.
9. Require private WebSocket health and startup reconciliation.
10. Promote challengers only from approved immutable experiments.
11. Resolve every ambiguous execution before retry.
12. Merge only after complete green CI and a documented rollback.

## Security

- Rotate any token or key exposed in chat, screenshots or logs.
- Separate read-only, Testnet and future Mainnet credentials.
- Disable withdrawals and transfers for automated keys.
- Keep production secrets outside Git, logs, metrics and Evidence payloads.
- Treat unexpected account, position or order state as a kill-switch event.
