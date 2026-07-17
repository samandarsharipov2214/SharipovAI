# SharipovAI OS

SharipovAI is a safety-first AI trading operating system built around verified
market evidence, deterministic risk controls, persistent experiments, realistic
Paper execution, walk-forward research and bounded Testnet shadow campaigns.

> **Current safety state:** Mainnet execution is compiled out. Testnet is disabled
> by default. The first real Testnet campaign is not considered launched until the
> deployed runtime produces actual authenticated private fills and the current head
> has complete green CI.

SharipovAI does not guarantee profit. It measures performance after spread, fees,
slippage, nonlinear market impact, funding, drawdown and execution failures.

- Binding policy: [`CONSTITUTION.md`](CONSTITUTION.md)
- First real Testnet runbook: [`docs/first-real-testnet-campaign.md`](docs/first-real-testnet-campaign.md)
- Legacy/Campaign Operations notes: [`docs/phase6-legacy-and-campaign-operations.md`](docs/phase6-legacy-and-campaign-operations.md)

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
monitoring, transport, idempotency and backtesting are infrastructure.

## Safety invariants

- `MAINNET_EXECUTION_COMPILED=False` cannot be overridden by environment variables.
- `EXECUTION_KILL_SWITCH=1` is the safe default.
- Dashboard, Telegram, strategies, schedulers, CLIs, agents and LLM output cannot
  submit raw orders.
- Exchange writes use `BybitExecutionClient.execute(ApprovedExecutionRequest)` only.
- Every request has a deterministic `sai_...` `orderLinkId` and durable reservation.
- Duplicate and ambiguous execution intents block blind retries.
- Testnet startup requires authenticated private `order` + `execution` health and
  restart-safe reconciliation.
- Scheduled campaigns accept only experiments manually approved for `testnet`.
- Every accepted campaign order remains within **10–25 USDT**.
- Completion requires **20+ matched** Paper/Testnet fills and zero orphan, duplicate,
  unmatched or unresolved evidence.
- Experiment, report, campaign and Champion/Challenger decisions never change runtime flags.
- Backtests and manual approvals cannot enable Mainnet.
- Secrets and runtime state stay outside Git, logs, metrics and experiment payloads.
- A partial, queued, skipped or classified failure is not green CI.

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
  -> active campaign authorization
  -> actual Bybit fee/instrument snapshot
  -> bounded Testnet shadow plan
  -> ApprovedExecutionRequest
  -> idempotency reservation
  -> Bybit Testnet submission
  -> private order topic
  -> private execution topic
  -> actual fee/partial-fill aggregation
  -> order/execution reconciliation
  -> Runtime Fill Harvester
  -> immutable final promotion report
  -> manual decision
```

A timeout after submission remains unresolved. It is never an automatic retry signal.

## Main components

| Component | Responsibility |
| --- | --- |
| `dashboard/` | FastAPI dashboard, lifecycle and protected administrative APIs |
| `dashboard/campaign_api.py` | Campaign schedules, cycles, reports and decisions |
| `dashboard/static/web2/campaign_operations_v36.js` | Campaign Operations schedules, progress, counters and readiness |
| `dashboard/static/web2/campaign_decision_v37.js` | Manual report-bound campaign decisions |
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
| `campaigns/core.py` | Campaign state machine, hard policy and immutable reports |
| `campaigns/orchestrator.py` | Non-overlapping approved campaign schedules |
| `campaigns/operations.py` | Operational read model and gated first campaign launcher |
| `campaigns/decisions.py` | Immutable report-bound manual decisions |
| `scripts/testnet_campaignctl.py` | Fail-closed operator CLI over canonical campaign services |
| `scripts/ci_runtime_state.py` | Self-hosted CI state reset and execution-safety audit |
| `scripts/legacy_contract_classifier.py` | Truth-preserving full-suite failure taxonomy |
| `validation/runtime_fill_harvester.py` | Actual order/execution evidence collection |
| `validation/fill_divergence.py` | Fill divergence metrics and policy |
| `experiments/` | Immutable research, promotion and leadership evidence |
| `trading_core/` | Event-driven backtest, funding, walk-forward and benchmarks |
| `historical_data/` | Versioned manifests, Parquet validation and DuckDB loading |
| `risk_engine/` | Hard limits and bounded soft-risk scaling |
| `storage/` | Canonical shared database and evidence ledger |

## Event-driven research

`EventDrivenBacktester` processes immutable events in strict `(timestamp_ms, symbol)`
order and models spread, maker/taker fees, deterministic slippage, nonlinear impact,
funding, risk allocation, mark-to-market equity and drawdown without future lookup.

`WalkForwardBacktester` uses sequential rolling or anchored out-of-sample windows.
Every candidate is compared on identical data and costs with buy-and-hold, trend,
breakout and mean-reversion benchmarks.

Historical manifests retain provenance, schema, symbol/time ranges, row count,
SHA-256 hashes, duplicates, price integrity and visible gaps. Missing intervals are
never fabricated.

## Experiment and promotion flow

`AutomaticExperimentRunner`:

1. validates the historical manifest;
2. derives a deterministic commit/manifest/config fingerprint;
3. refuses identical duplicate experiments;
4. runs walk-forward evaluation and mandatory benchmarks;
5. writes validation and results once with SHA-256 references;
6. marks incomplete work failed;
7. cannot enable execution or appoint a champion.

Promotion remains staged:

```text
READ_ONLY -> PAPER -> TESTNET -> CONTROLLED_MAINNET -> SCALE
```

Every automated gate is followed by a separate manual decision. Failed gates cannot
be manually overridden.

## Private execution evidence

The private WebSocket subscribes to:

```text
order
execution
```

`BybitExecutionStateStore` persists each `execId` once and aggregates actual fee,
fee currency, maker/taker state, quantity, value, weighted fill price, timestamps,
partial fills, replay counts and conflicting identities by `orderLinkId`.

Reconciliation blocks:

- executed order without execution rows;
- execution rows without a private order;
- cumulative quantity mismatch;
- conflicting duplicate `execId`;
- one `orderLinkId` mapped to multiple order IDs;
- unresolved submission outcome.

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
| Actual private execution fees | Present |
| Private stream and reconciliation | Healthy |

Trades created before campaign activation are not attached to a new campaign.
An out-of-range order or any identity failure hard-blocks the campaign.

## Campaign Operations dashboard

The `Кампании` page exposes:

- persisted schedules and next-run time;
- the single active authorization;
- matched-fill progress and remaining fills;
- orphan, duplicate and unresolved counters;
- campaign-bound actual fee totals;
- final-report readiness and immutable report status;
- manual approval/rejection tokens and decision history.

Relevant routes:

| Route | Purpose |
| --- | --- |
| `/#campaigns` | Campaign Operations Web2 page |
| `/api/campaigns/operations` | Complete operations snapshot |
| `/api/campaigns/first-testnet/plan` | Exact first-campaign readiness gates |
| `/api/campaigns/first-testnet/start` | Gated bounded campaign start |
| `/api/campaigns/orchestrator/status` | Scheduler state |
| `/api/campaigns/orchestrator/tick` | Admin scheduler cycle |
| `/api/campaigns/schedules` | List/create approved schedules |
| `/api/campaigns/{id}/run` | Run one campaign cycle |
| `/api/campaigns/{id}/promotion-report` | Generate/read immutable final report |
| `/api/campaigns/{id}/decision` | Read/write manual report-bound decision |
| `/api/exchange/private-order-ws/snapshot` | Private order/execution reconciliation |
| `/api/validation/fill-harvester/status` | Runtime divergence harvester |

Administrative mutation endpoints require authentication. None exposes a raw order primitive.

## Operator CLI

Read-only snapshot:

```bash
python scripts/testnet_campaignctl.py snapshot
```

Exact readiness plan:

```bash
python scripts/testnet_campaignctl.py plan \
  --experiment-id '<promoted-experiment-id>' \
  --confirmation I_APPROVE_BOUNDED_TESTNET_SHADOW_CAMPAIGN
```

Start the first campaign only after all deployed gates are green:

```bash
python scripts/testnet_campaignctl.py start \
  --experiment-id '<promoted-experiment-id>' \
  --scope BTCUSDT \
  --actor '<authenticated-operator>' \
  --confirmation I_APPROVE_BOUNDED_TESTNET_SHADOW_CAMPAIGN
```

Additional write commands use distinct confirmations:

```text
cycle    -> I_APPROVE_BOUNDED_TESTNET_CAMPAIGN_CYCLE
report   -> I_APPROVE_IMMUTABLE_CAMPAIGN_REPORT
decision -> I_APPROVE_MANUAL_CAMPAIGN_DECISION
```

The CLI cannot set flags, install credentials, disable the kill switch or enable Mainnet.
See the complete procedure in `docs/first-real-testnet-campaign.md`.

## CI cleanroom

Self-hosted runners reuse workspaces. Repository-wide `conftest.py` now executes a
fail-closed cleanroom before every GitHub Actions pytest process.

It:

1. verifies the kill switch and disabled execution flags;
2. rejects production Bybit mode/base URL and a green release gate;
3. removes only explicitly configured SQLite/WAL/journal/runtime-state targets;
4. allows deletion only inside the GitHub workspace or `/tmp`;
5. retains `artifacts/runtime-state-<pid>.json`;
6. blocks test collection on unsafe state.

Dry-run audit:

```bash
python scripts/ci_runtime_state.py
```

Authorized CI reset:

```bash
GITHUB_ACTIONS=true python scripts/ci_runtime_state.py \
  --apply \
  --report artifacts/runtime-reset.json
```

The cleanroom does not scan arbitrary directories and must never be pointed at
production runtime paths.

## Legacy failure taxonomy

`scripts/legacy_contract_classifier.py` assigns every full-suite failure to exactly one:

- `regression`;
- `stale_test`;
- `environment_contamination`.

Unknown failures are regressions. Classification cannot convert failed, missing,
queued or skipped CI into success.

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

These defaults do not enable exchange writes. Mainnet remains unavailable even when
environment variables are changed.

## Development setup

Python 3.12 is required.

```bash
python -m venv .venv
source .venv/bin/activate  # Windows PowerShell: .venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements-dev.txt
```

Core verification:

```bash
python -m pip check
python -m pip_audit -r requirements.txt --progress-spinner off
python -m compileall -q .
python scripts/execution_foundation_audit.py
python scripts/research_foundation_audit.py --json
python scripts/promotion_foundation_audit.py --json
python scripts/campaign_foundation_audit.py --json
python -m pytest tests/test_ci_runtime_state.py tests/test_testnet_campaignctl.py -q --tb=short
python -m pytest -q --tb=short
```

CI retains dependency audit, coverage, JUnit, targeted suite logs, full pytest logs,
legacy classification and compact failure reports. Merge only after complete factual green CI.

## Security

- Rotate any key exposed in chat, screenshots or logs.
- Separate read-only, Testnet and future Mainnet credentials.
- Disable withdrawal and transfer permissions.
- Never commit `.env`, database files, state snapshots or credentials.
- Keep the kill switch active outside an explicitly authorized bounded Testnet campaign.
