# SharipovAI OS

SharipovAI is a safety-first AI trading operating system for event-driven research,
realistic Paper execution and bounded Testnet shadow campaigns.

> **Safety state:** Mainnet execution is compiled out. Mainnet remains unavailable.
> Testnet execution is disabled by default. No campaign is successful without
> authenticated private Testnet fills, actual fees and complete green CI.

SharipovAI does not guarantee profit. Results are reported after spread, maker/taker
fees, slippage, nonlinear market impact, funding, drawdown and execution failures.

- Binding policy: [`CONSTITUTION.md`](CONSTITUTION.md)
- Deep production audit: [`docs/phase11-deep-audit-report.md`](docs/phase11-deep-audit-report.md)
- Controlled scaling: [`docs/phase10-controlled-scaling-performance.md`](docs/phase10-controlled-scaling-performance.md)
- First real Testnet runbook: [`docs/first-real-testnet-campaign.md`](docs/first-real-testnet-campaign.md)

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

Storage, validation, observability, experiment registry, historical data, scheduling,
campaign orchestration, idempotency and dashboards are infrastructure.

## Non-negotiable safety invariants

- `MAINNET_EXECUTION_COMPILED=False` cannot be overridden by environment variables.
- `EXECUTION_KILL_SWITCH=1` is the safe default.
- Dashboard, Telegram, schedulers, agents, LLM output and CLIs cannot submit raw orders.
- Exchange writes use `BybitExecutionClient.execute(ApprovedExecutionRequest)` only.
- Every request has a deterministic `sai_...` `orderLinkId` and durable reservation.
- Duplicate or ambiguous execution outcomes block blind retries.
- Testnet startup requires authenticated private `order` and `execution` streams,
  fresh persisted heartbeats and restart-safe reconciliation.
- Scheduled campaigns use only experiments manually approved for `testnet`.
- Initial accepted Testnet orders remain within **10–25 USDT**.
- Completion requires **20+ matched** Paper/Testnet fills and **zero orphan**, duplicate,
  unmatched or unresolved identities.
- Backtests, reports, promotion decisions and scaling plans never enable Mainnet.
- Secrets and runtime state stay outside Git, logs, metrics and experiment payloads.
- Queued, skipped, missing or classified failures are not green CI.

## Canonical execution path

```text
Verified market evidence
  -> Portfolio snapshot
  -> Risk Engine hard limits
  -> Correlation-aware capital allocation
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
  -> actual fee and partial-fill aggregation
  -> order/execution reconciliation
  -> Runtime Fill Harvester
  -> immutable final promotion report
  -> manual decision
```

A timeout after submission is an ambiguous financial outcome, not a retry signal.

## Research and backtesting

`EventDrivenBacktester` processes immutable events in strict `(timestamp_ms, symbol)`
order. It models spread, fees, deterministic slippage, nonlinear impact, funding,
mark-to-market equity and drawdown without future lookup.

`WalkForwardBacktester` uses sequential rolling or anchored out-of-sample windows.
Every candidate is compared with buy-and-hold, trend, breakout and mean-reversion
benchmarks on identical data and costs.

`historical_data/` stores versioned historical manifests with provenance, schema,
symbol/time ranges, row counts, SHA-256 hashes, duplicates, price integrity and visible
gaps. Missing intervals are never fabricated. DuckDB is used for validated historical
loading.

Operational observability includes structured logs, Prometheus metrics at `/metrics`,
read-only execution status and actual fee totals.

## Experiment and promotion flow

The persistent experiment registry stores immutable experiment identity, commit,
manifest, configuration, walk-forward results, benchmarks, Paper results and manual
promotion evidence.

```text
READ_ONLY -> PAPER -> TESTNET -> CONTROLLED_MAINNET -> SCALE
```

Every automated promotion gate is followed by a separate manual decision. Failed
automated gates cannot be overridden.

Important surfaces:

- `experiments/` — persistent experiment registry and Champion/Challenger evidence;
- `validation/fill_divergence.py` — Paper/Testnet fill divergence;
- `/backtest-results` — experiment results UI contract;
- `/experiment-comparison` — experiment comparison UI contract;
- `FEATURE_BYBIT_PRIVATE_ORDER_WS=0` — private stream is off by default.

## Private order and execution evidence

The authenticated read-only private WebSocket subscribes to:

```text
order
execution
```

Canonical private execution evidence records `execId`, order identity, quantity, price,
value, timestamps, maker/taker state, actual fee amount and fee currency. Exact replay is
deduplicated. Conflicting `execId`, orphan executions, missing execution rows, quantity
mismatch or unresolved submissions block reconciliation.

## Bounded Testnet campaign

| Gate | Required |
| --- | ---: |
| Per-order initial Testnet notional | 10–25 USDT |
| Matched Paper/Testnet fills | 20+ |
| Unmatched Paper fills | 0 |
| Unmatched Testnet fills | 0 |
| Orphan order/execution evidence | 0 |
| Duplicate or conflicting identities | 0 |
| Unresolved execution intents | 0 |
| Actual private fees | Present |
| Private stream | Fresh and authenticated |
| Reconciliation | Restart-safe |

Trades created before campaign activation are not attached to a new campaign. Synthetic
fills, screenshots and copied JSON are not private execution evidence.

## Phase 9 results and scaling preparation

Phase 9 calculates FIFO realized PnL, actual fees, win rate, profit factor, drawdown and
Paper/Testnet divergence. Scaling preparation remains evidence-only and requires a
separate manual decision.

## Phase 10 controlled scaling and performance

A controlled scaling authority:

- requires two clean campaigns and an eligible Phase 9 plan;
- requires exact confirmation `I_APPROVE_CONTROLLED_TESTNET_NOTIONAL_SCALING`;
- increases notional by at most `1.5x`;
- never exceeds `50 USDT`;
- is Testnet-only, scope-bound, expiring and SHA-256 protected;
- uses one persistent global optimistic lock;
- fails closed when expired, revoked, tampered or lock-mismatched;
- cannot bypass the kill switch or create a second execution path.

Missing correlation data is not treated as zero. Correlation-aware sizing blocks on
missing/invalid evidence and uses the smallest remaining risk, volatility, position,
cluster, authority and absolute-cap capacity.

Phase 9 reports create immutable Phase 10 performance snapshots. Monthly reports retain
history by evidence-derived IDs and include net PnL, fees, matched fills and maximum
drawdown.

## Phase 11 production audit

`ProductionAudit` verifies:

- compile and runtime execution locks;
- authentication, database-required and sandbox configuration;
- canonical database health for SQLite or PostgreSQL;
- tracked secret-file hygiene;
- deployment provenance and atomic verification;
- responsive and injection-safe dashboard contracts;
- Phase 10/11 crash tests in mandatory CI;
- a finite Testnet ceiling at or below 50 USDT.

The deterministic audit SHA-256 excludes timestamps and host metadata. Identical audited
state produces the same evidence hash.

Read-only admin endpoints:

```text
GET /api/production/phase11/audit
GET /api/production/phase11/overview
GET /api/campaigns/phase10/activations
GET /api/performance/phase10/overview
```

Sensitive Phase 10/11 routes are authorized by middleware before request body parsing.

## Dashboard

The Web2 dashboard retains Campaign Operations, Live Monitoring, Campaign Analysis,
Scaling and Performance Overview. Phase 10/11 panels use:

- safe DOM creation with `textContent` and `replaceChildren`;
- no `innerHTML`, `insertAdjacentHTML` or `eval`;
- request timeout and `AbortController`;
- exponential retry backoff;
- pause while offline or hidden;
- truthful missing-data states;
- dark/light/system themes;
- mobile grids, 44 px controls, visible keyboard focus and reduced-motion support.

## Operator control plane

The operator CLI uses canonical services:

```bash
python scripts/testnet_campaignctl.py snapshot
python scripts/testnet_campaignctl.py plan \
  --experiment-id '<approved-experiment>' \
  --confirmation I_APPROVE_BOUNDED_TESTNET_SHADOW_CAMPAIGN
```

Write commands require distinct exact confirmations. The operator control plane cannot
install credentials, change environment flags, disable the kill switch, deploy code or
enable Mainnet.

## CI cleanroom

Every GitHub Actions pytest process runs the fail-closed CI cleanroom before application
imports. It verifies safe flags, rejects production exchange state, removes only explicit
workspace or `/tmp` state and retains JSON evidence.

Phase 11 adds a separate `Phase 11 Hardening` workflow for:

- dependency audit and compilation;
- controlled-scaling crash tests;
- correlation-risk crash tests;
- production audit tests;
- dashboard/security contracts;
- deterministic audit evidence.

Core verification:

```bash
python -m pip install -r requirements-dev.txt
python -m pip check
python -m pip_audit -r requirements.txt --progress-spinner off
python -m compileall -q .
python scripts/execution_foundation_audit.py
python scripts/research_foundation_audit.py --json
python scripts/promotion_foundation_audit.py --json
python scripts/campaign_foundation_audit.py --json
python -m pytest \
  tests/test_phase10_controlled_scaling.py \
  tests/test_phase10_capital_engine.py \
  tests/test_phase11_production_audit.py \
  tests/test_phase11_dashboard_contract.py \
  tests/test_phase11_crash_resilience.py \
  -q --tb=short
python -m pytest -q --tb=short
```

## Deployment

```bash
export SHARIPOVAI_EXPECTED_SHA="$(git rev-parse HEAD)"
sudo -E bash deploy/vps/phase11_release_preflight.sh
# Deploy exactly SHARIPOVAI_EXPECTED_SHA
sudo -E bash deploy/vps/phase11_post_deploy_verify.sh
sudo bash deploy/vps/install_phase10_monthly_monitor.sh
```

Deployment remains blocked when the worktree is dirty, the SHA differs, the database is
unhealthy, auth is disabled, an execution flag is enabled, the kill switch is off or the
audit has blockers.

## Safe environment defaults

```env
EXCHANGE_MODE=sandbox
EXCHANGE_BASE_URL=https://api-testnet.bybit.com
EXCHANGE_LIVE_TRADING_ENABLED=0
FEATURE_BYBIT_LIVE_EXECUTION=0
FEATURE_BYBIT_TESTNET_EXECUTION=0
TESTNET_EXECUTION_ENABLED=0
AUTONOMOUS_TESTNET_ENABLED=0
AUTONOMOUS_TESTNET_BRIDGE_ENABLED=0
FEATURE_BYBIT_PRIVATE_ORDER_WS=0
BYBIT_ALLOW_LEGACY_EXCHANGE_CREDENTIALS=0
EXECUTION_KILL_SWITCH=1
SHARIPOVAI_DISABLE_AUTH=0
SHARIPOVAI_DATABASE_REQUIRED=1
PHASE11_MAX_TESTNET_NOTIONAL_USDT=50
```

## Security

- Rotate any key exposed in chat, screenshots or logs.
- Separate read-only, Testnet and any future Mainnet credentials.
- Disable withdrawal and transfer permissions.
- Never commit `.env`, database files, state snapshots or credentials.
- Keep the kill switch active outside an explicitly authorized finite Testnet window.
