# SharipovAI OS

SharipovAI is a safety-first AI trading operating system built around verified
market evidence, deterministic risk controls, persistent experiments, realistic
Paper execution, walk-forward research and bounded Testnet shadow campaigns.

> **Current safety state:** Mainnet execution is compiled out. Testnet is disabled
> by default and requires `ApprovedExecutionRequest`, durable idempotency, actual
> Bybit instrument rules, authenticated private `order` + `execution` topics and
> successful reconciliation.

SharipovAI does not guarantee profit. It measures performance after spread, fees,
slippage, nonlinear market impact, funding, drawdown and execution failures.

Binding policy: [`CONSTITUTION.md`](CONSTITUTION.md).
Phase 6 runbook: [`docs/phase6-legacy-and-campaign-operations.md`](docs/phase6-legacy-and-campaign-operations.md).

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

Storage, validation, scheduling, campaign orchestration, experiment registries,
monitoring, transport, idempotency and backtesting are infrastructure, not extra AI organs.

## Safety invariants

- `MAINNET_EXECUTION_COMPILED=False` cannot be overridden by environment variables.
- `EXECUTION_KILL_SWITCH=1` is the safe default.
- Dashboard, Telegram, strategies, schedulers, agents and LLM output cannot submit raw orders.
- Exchange writes use `BybitExecutionClient.execute(ApprovedExecutionRequest)` only.
- Every request has a deterministic `sai_...` `orderLinkId` and durable reservation.
- Duplicate and ambiguous execution intents block blind retries.
- Testnet startup requires private stream health and reconciliation.
- Private stream must subscribe to both `order` and `execution`.
- Scheduled campaigns accept only manually approved Testnet experiments.
- Every campaign order must remain within **10–25 USDT**.
- Campaign completion requires **20 matched** fills and **zero orphan**, duplicate,
  unmatched and unresolved evidence.
- Experiment, final report and Champion / Challenger decisions never change runtime flags.
- Backtests and manual approvals cannot enable Mainnet.
- Secrets and runtime state stay outside Git, logs, metrics and experiment payloads.
- Legacy failure classification never changes a failed CI result into success.
- The first bounded Testnet campaign additionally requires the explicit Phase 6 release gate
  and the exact campaign confirmation phrase.

## Main components

| Component | Responsibility |
| --- | --- |
| `dashboard/` | FastAPI dashboard, lifecycle and protected administrative APIs |
| `dashboard/routers/execution_status.py` | Read-only execution, risk and Paper PnL status |
| `dashboard/routers/experiments.py` | Backtest results and experiment comparison |
| `dashboard/routers/leadership.py` | Champion / Challenger comparison and manual leadership UI |
| `dashboard/campaign_api.py` | Scheduled campaign, cycle, operations and final report control plane |
| `dashboard/fill_harvester_api.py` | Runtime fill-validation status and manual trigger |
| `dashboard/static/web2/campaign_operations_v36.js` | Schedules, active campaign, fill progress, identity and fee evidence UI |
| `trading_candidate.py` | Fail-closed analytical candidate contract |
| `exchange_connector/execution_contract.py` | Immutable approved execution envelope |
| `exchange_connector/execution_idempotency.py` | Durable duplicate/unresolved protection |
| `exchange_connector/bybit_reference_data.py` | Actual account fee tier and instrument filters |
| `exchange_connector/bybit_order_state.py` | Private order lifecycle state |
| `exchange_connector/bybit_execution_state.py` | Actual execution fees and partial-fill ledger |
| `exchange_connector/bybit_private_order_ws.py` | Read-only authenticated order + execution topics |
| `exchange_connector/private_ws_gate.py` | Persistent stream readiness/heartbeat gate |
| `autonomous_trading/shadow_mode.py` | Bounded Paper/Testnet shadow planning |
| `autonomous_trading/shadow_bridge.py` | Campaign-aware canonical Testnet bridge |
| `autonomous_trading/startup_reconciliation.py` | Intent, journal, order and stream reconciliation |
| `campaigns/core.py` | Campaign state machine, policy and immutable final reports |
| `campaigns/orchestrator.py` | Non-overlapping approved campaign schedules |
| `campaigns/operations.py` | Operational read model and gated first Testnet campaign launcher |
| `scripts/legacy_contract_classifier.py` | Truth-preserving full-suite failure taxonomy |
| `capital_allocation.py` | Reserve, risk, symbol and correlation allocation |
| `risk_engine/` | Hard limits and bounded soft-risk scaling |
| `trading_core/` | Event-driven backtest, funding, walk-forward and benchmarks |
| `historical_data/` | Versioned manifests, Parquet validation and DuckDB loading |
| `experiments/registry.py` | ExperimentRegistry persistence and promotion evidence |
| `experiments/runner.py` | Automatic immutable experiment runner |
| `experiments/champion_challenger.py` | Evidence-gated strategy leadership |
| `validation/fill_divergence.py` | FillDivergenceAnalyzer and policy tolerances |
| `validation/runtime_fill_harvester.py` | Actual runtime order/execution evidence collection |
| `observability/` | Structured JSON logs and Prometheus-ready metrics |
| `storage/` | Canonical shared database and evidence ledger |

## Canonical execution path

```text
Verified market evidence
  -> Portfolio snapshot
  -> Risk Engine hard limits
  -> Capital allocation
  -> Decision Quality
  -> Security Guard
  -> TradingCandidate validation
  -> Paper execution
  -> active scheduled campaign authorization
  -> Bybit fee/instrument snapshot
  -> bounded Testnet shadow plan
  -> ApprovedExecutionRequest
  -> idempotency reservation
  -> Bybit Testnet submission
  -> private order topic
  -> private execution topic
  -> actual fee/partial-fill aggregation
  -> order/execution reconciliation
  -> Runtime Fill Harvester
  -> final promotion report
  -> manual decision
```

A timeout after submission remains unresolved. It is never an automatic retry signal.

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
- no future lookup or fabricated fill.

`WalkForwardBacktester` supports sequential rolling and anchored out-of-sample
windows. Every candidate is compared on identical data and costs against:

- buy-and-hold;
- trend following;
- breakout;
- mean reversion.

## Historical data

`historical_data` validates versioned manifests before creating `MarketEvent` objects.
It checks provenance, schema, symbol/time ranges, row count, SHA-256 hashes,
duplicates, price integrity and gaps, then queries Parquet through DuckDB.

```bash
python scripts/validate_historical_data.py data/history/manifest.json
```

Missing intervals remain visible. The loader never fabricates bars or trades.

## Automatic experiments

`AutomaticExperimentRunner`:

1. validates the historical manifest;
2. derives a deterministic commit/manifest/config fingerprint;
3. refuses an identical duplicate experiment;
4. runs walk-forward evaluation;
5. runs mandatory benchmarks;
6. writes validation, walk-forward, benchmark and run-summary results once;
7. stores immutable result SHA-256 values in `ExperimentRegistry`;
8. marks incomplete work failed.

```python
from campaigns import ScheduledCampaignOrchestrator
from experiments import AutomaticExperimentRequest, AutomaticExperimentRunner

experiment = AutomaticExperimentRunner().run(
    AutomaticExperimentRequest(
        commit_sha="<commit>",
        strategy_name="trend_candidate_v1",
        strategy_config={"fast": 20, "slow": 100},
        backtest_config=backtest_config,
        walk_forward_config=walk_forward_config,
        manifest_path="data/history/manifest.json",
    ),
    walk_forward_strategy_factory=strategy_factory,
    benchmark_strategy_factory=benchmark_factory,
)
```

The runner cannot enable execution or appoint a champion.

## Actual Bybit reference data

Testnet shadow planning reads:

```text
GET /v5/account/fee-rate
GET /v5/market/instruments-info
```

Persisted evidence includes maker/taker rate, `tickSize`, `qtyStep`, minimum quantity,
minimum notional, maximum market quantity, environment, source and expiration.
Quantity is rounded down. Missing or stale data blocks execution.

## Private execution topic

`BybitPrivateOrderWebSocket` subscribes to:

```text
order
execution
```

`BybitExecutionStateStore` persists each `execId` once and aggregates by
`orderLinkId`:

- actual `execFee` and `feeCurrency`;
- maker/taker status and `feeRate`;
- execution quantity/value;
- weighted average fill price;
- first/last execution time;
- multiple partial fills;
- exact replay count;
- conflicting identity count.

Order and execution reconciliation blocks:

- executed order without execution rows;
- execution rows without a private order;
- cumulative quantity mismatch;
- conflicting duplicate `execId`;
- one `orderLinkId` mapped to multiple order IDs.

## Scheduled Campaign Orchestrator

The Scheduled Campaign Orchestrator launches only experiments that already have:

- completed research evidence;
- passed automated Testnet promotion report;
- explicit manual Testnet approval.

Creating a schedule:

```python
from campaigns import ScheduledCampaignOrchestrator

orchestrator = ScheduledCampaignOrchestrator()
schedule = orchestrator.create_schedule(
    experiment_id="exp_...",
    scope="spot:testnet",
    interval_seconds=300,
    actor="owner",
)
```

A due schedule creates a campaign authorization. It does not enable exchange flags or
bypass the canonical bridge.

## Testnet Shadow Campaign

Hard campaign policy:

| Gate | Required |
| --- | ---: |
| Per-order Testnet notional | 10–25 USDT |
| Matched Paper/Testnet fills | 20+ |
| Unmatched Paper fills | 0 |
| Unmatched Testnet fills | 0 |
| Orphan order/execution evidence | 0 |
| Duplicate order identities | 0 |
| Conflicting execution identities | 0 |
| Unresolved execution intents | 0 |
| Actual private execution fees | Required |
| Private stream and reconciliation | Healthy |

Trades created before campaign activation are not attached to a new campaign.
An out-of-range order, orphan, duplicate or unresolved identity hard-blocks the campaign.

## Phase 6 Legacy Contract Stabilization

`scripts/legacy_contract_classifier.py` parses the full-suite JUnit artifact and assigns
every failure to exactly one class:

- `regression` — current behavior is broken or unresolved;
- `stale_test` — a test targets a retired API, exact asset version or obsolete copy;
- `environment_contamination` — runner package layout, shared state, credentials or an
  external dependency invalidated the result.

Unknown failures default to `regression`. The current 100-failure baseline classified as
61 regressions, 30 stale tests and 9 environment-contamination failures. These counts are
diagnostic evidence, not a release waiver.

```bash
python scripts/legacy_contract_classifier.py \
  --junit artifacts/pytest.xml \
  --json artifacts/legacy-contract-classification.json \
  --markdown artifacts/legacy-contract-classification.md
```

Compatibility adapters preserve current production ownership:

- configured administrator priority is independent of import order;
- the global auth guard and legacy test hooks resolve the same signed session;
- News restore aliases route to the canonical DB-backed network;
- Telegram command-menu restore remains separate from canonical Mini App setup;
- execution and Testnet bridge tests use current canonical evidence semantics.

## Campaign Operations and first bounded Testnet run

The `Кампании` Web2 page and `CampaignOperationsService` expose schedules, the single
active authorization, fill progress, identity-integrity counters, actual execution fees
and final-report readiness.

The first bounded Testnet start endpoint requires every existing safety gate plus:

```text
PHASE6_TESTNET_RELEASE_GATE=green
I_APPROVE_BOUNDED_TESTNET_SHADOW_CAMPAIGN
```

Application code does not set the release-gate environment value or enable execution
flags. The first campaign is not considered executed until actual Bybit Testnet private
execution evidence contains at least 20 matched fills with zero orphan, duplicate,
unmatched and unresolved records. Completion generates the existing immutable final
promotion report automatically. Promotion remains manual.

## Runtime fill validation

`RuntimeFillHarvester` joins:

```text
Paper trade
  <-> campaign bridge record
  <-> orderLinkId
  <-> private order state
  <-> private execution rows
```

`FillDivergenceAnalyzer` measures:

- first-fill latency;
- signed slippage;
- requested versus filled quantity;
- partial-fill rate;
- actual fee divergence;
- unmatched fills.

The report fingerprint includes immutable execution IDs. Re-reading unchanged evidence
returns the existing report rather than creating a conflicting result.

## Final Promotion Report

`FinalPromotionReportEngine` combines:

- immutable experiment evidence;
- campaign metrics;
- fill-divergence report;
- private stream health;
- startup reconciliation;
- order/execution reconciliation;
- actual execution fee evidence;
- zero orphan/duplicate/unresolved gates.

It returns only `eligible_for_manual_decision` or `blocked`. A final promotion report
cannot change flags, capital, deployment or Mainnet state.

## Champion / Challenger

The `/champion-challenger` page shows one champion and active challengers for a bounded
scope. It uses the same immutable experiment comparison metrics.

Manual leadership promotion requires:

```text
PROMOTE:<scope>:<experiment_id>:<target_stage>
```

The experiment must already have passed automated gates and manual stage approval.
Leadership updates preserve actor, reason, prior champion, timestamp and evidence SHA-256.
They do not deploy code or enable execution.

## Dashboard routes

Start locally:

```bash
uvicorn dashboard:app --reload
```

| Route | Purpose |
| --- | --- |
| `/execution-status` | Read-only execution, risk, exposure and Paper PnL |
| `/backtest-results` | Persistent ExperimentRegistry results |
| `/experiment-comparison?ids=exp-a,exp-b` | Side-by-side OOS comparison |
| `/champion-challenger?scope=spot:testnet` | Champion / Challenger UI |
| `/#campaigns` | Campaign Operations Web2 page |
| `/api/experiments` | Experiment JSON |
| `/api/strategy-leadership/{scope}` | Leadership snapshot and comparison |
| `/api/campaigns/orchestrator/status` | Scheduler state |
| `/api/campaigns/orchestrator/tick` | Admin scheduler cycle |
| `/api/campaigns/operations` | Schedules, active campaign, fills, identity, fees and report readiness |
| `/api/campaigns/first-testnet/plan` | Exact first-campaign release gates |
| `/api/campaigns/first-testnet/start` | Gated bounded Testnet campaign start |
| `/api/campaigns/schedules` | List/create approved schedules |
| `/api/campaigns` | Campaign registry |
| `/api/campaigns/{id}/run` | Admin campaign cycle |
| `/api/campaigns/promotion-reports` | Final reports |
| `/api/campaigns/{id}/promotion-report` | Generate final report |
| `/api/exchange/private-order-ws/snapshot` | Order + execution state and reconciliation |
| `/api/validation/fill-harvester/status` | Harvester status |
| `/metrics` | Protected Prometheus text endpoint |

Administrative mutation endpoints require authentication. None exposes a raw order primitive.

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
SCHEDULED_CAMPAIGN_ORCHESTRATOR_ENABLED=0
PHASE6_TESTNET_RELEASE_GATE=blocked
EXECUTION_KILL_SWITCH=1
EXECUTION_MAX_NOTIONAL_USDT=25
SHADOW_TESTNET_MAX_NOTIONAL_USDT=25
CAMPAIGN_ORCHESTRATOR_TICK_SECONDS=10
BYBIT_PRIVATE_WS_GATE_MAX_AGE_SECONDS=60
```

These values do not enable exchange writes. Mainnet remains unavailable even when
environment variables are changed.

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
  tests/test_bybit_execution_state.py \
  tests/test_private_execution_ws.py \
  tests/test_runtime_fill_harvester.py \
  tests/test_scheduled_campaign_orchestrator.py \
  tests/test_final_promotion_report.py \
  tests/test_leadership_dashboard.py \
  -q --tb=short

python -m pytest \
  tests/test_legacy_contract_classifier.py \
  tests/test_admin_auth_priority.py \
  tests/test_auth_guard_middleware.py \
  dashboard/tests/test_news_agent_network_api.py \
  tests/test_telegram_menu_button.py \
  tests/test_execution_stages.py \
  tests/test_testnet_bridge.py \
  tests/test_campaign_operations.py \
  tests/test_campaign_operations_ui.py \
  -q --tb=short

python -m pytest -q --tb=short
```

CI retains dependency audit, coverage, JUnit, Phase 5/6 targeted logs, full pytest logs,
legacy classification JSON/Markdown and compact failure reports. Classification cannot
make a partial, failed, queued or skipped suite green.

## Development workflow

1. Work in a branch and keep the PR draft until factual checks pass.
2. Keep Testnet/Mainnet disabled by default.
3. Record every research run in `ExperimentRegistry`.
4. Validate every manifest and benchmark every candidate.
5. Schedule only an experiment manually approved for Testnet.
6. Collect private `order` and `execution` evidence.
7. Require 20+ matched fills and zero identity failures.
8. Generate a final report for a separate manual decision.
9. Resolve every ambiguous execution before retry.
10. Classify legacy failures but fix them before release.
11. Merge only after complete green CI and documented rollback.

## Security

- Rotate any key exposed in chat, screenshots or logs.
- Separate read-only, Testnet and future Mainnet credentials.
- Disable withdrawal/transfer permissions.
- Never commit `.env`, database files, state snapshots or credentials.
- Keep the kill switch active outside an explicitly authorized Testnet campaign.
