# SharipovAI OS

SharipovAI is a safety-first AI trading operating system for event-driven research,
realistic Paper execution and bounded Testnet shadow campaigns.

> **Safety state:** Mainnet execution is compiled out. Mainnet remains unavailable.
> Testnet execution is disabled by default. No campaign is successful without
> authenticated private Testnet fills, actual fees and complete green CI.

SharipovAI does not guarantee profit. Results are measured after spread, maker/taker
fees, slippage, nonlinear impact, funding, drawdown and execution failures.

- Binding policy: [`CONSTITUTION.md`](CONSTITUTION.md)
- Production launch: [`docs/phase11-production-launch.md`](docs/phase11-production-launch.md)
- Deep audit: [`docs/phase11-deep-audit-report.md`](docs/phase11-deep-audit-report.md)
- Controlled scaling: [`docs/phase10-controlled-scaling-performance.md`](docs/phase10-controlled-scaling-performance.md)
- First real Testnet campaign: [`docs/first-real-testnet-campaign.md`](docs/first-real-testnet-campaign.md)

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
- `EXECUTION_KILL_SWITCH=1` is the production-safe default.
- Dashboard, Telegram, schedulers, agents, LLM output and CLIs cannot submit raw orders.
- Exchange writes use `BybitExecutionClient.execute(ApprovedExecutionRequest)` only.
- Every request has a deterministic `sai_...` `orderLinkId` and durable reservation.
- Duplicate or ambiguous outcomes block blind retries.
- Testnet startup requires authenticated private `order` and `execution` streams,
  fresh heartbeats and restart-safe reconciliation.
- Initial accepted Testnet orders remain within **10–25 USDT**.
- Completion requires **20+ matched** Paper/Testnet fills and **zero orphan**, duplicate,
  unmatched or unresolved identities.
- Backtests, reports, manual decisions and scaling plans never enable Mainnet.
- Secrets and runtime state stay outside Git, logs, metrics and experiment payloads.
- Queued, skipped, missing, cancelled or classified failures are not green CI.

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

`WalkForwardBacktester` uses sequential rolling or anchored walk-forward out-of-sample
windows. Every candidate is compared with buy-and-hold, trend, breakout and
mean-reversion benchmarks on identical data and costs.

`historical_data/` stores versioned historical manifests with provenance, schema,
symbol/time ranges, row count, SHA-256, duplicates, price integrity and visible gaps.
Missing intervals are never fabricated. DuckDB loads validated historical data.

Operational observability includes structured logs, Prometheus metrics at `/metrics`,
read-only execution status at `/execution-status` and actual fee totals.

## Experiment and promotion flow

The persistent experiment registry under `experiments/` stores immutable experiment
identity, commit, manifest, configuration, walk-forward results, benchmarks, Paper
results and manual promotion evidence.

```text
READ_ONLY -> PAPER -> TESTNET -> CONTROLLED_MAINNET -> SCALE
```

Every automated promotion gate is followed by a separate manual decision. Failed
automated gates cannot be overridden.

Important surfaces:

- `validation/fill_divergence.py` — Paper/Testnet fill divergence;
- `/backtest-results` — experiment results;
- `/experiment-comparison` — Champion/Challenger comparison;
- `FEATURE_BYBIT_PRIVATE_ORDER_WS=0` — private stream off by default.

## Private execution evidence

Canonical private order and execution evidence records `execId`, order identity,
quantity, price, value, timestamps, maker/taker state, actual fee amount and currency.
Exact replay is deduplicated. Conflicting `execId`, orphan executions, missing rows,
quantity mismatch or unresolved submissions block reconciliation.

Synthetic fills, screenshots, copied JSON and a campaign row are not private execution
evidence.

## Bounded Testnet campaign

| Gate | Required |
| --- | ---: |
| Initial per-order Testnet notional | 10–25 USDT |
| Matched Paper/Testnet fills | 20+ |
| Unmatched Paper/Testnet fills | 0 |
| Orphan order/execution evidence | 0 |
| Duplicate/conflicting identities | 0 |
| Unresolved execution intents | 0 |
| Actual private fees | Present |
| Private streams | Fresh and authenticated |
| Reconciliation | Restart-safe |

Trades created before campaign activation are not attached to a new campaign.

## Phase 9 immutable results

Phase 9 calculates FIFO realized PnL, actual fees, win rate, profit factor, drawdown and
Paper/Testnet divergence. Reports use evidence-derived IDs, are append-only and retain a
separate latest index. Scaling rejects a corrupted report and deduplicates campaigns.

## Phase 10 controlled scaling

A scaling authority:

- requires two distinct clean campaigns and a SHA-256 protected Phase 9 plan;
- requires `I_APPROVE_CONTROLLED_TESTNET_NOTIONAL_SCALING`;
- increases notional by at most `1.5x` and never above `50 USDT`;
- is Testnet-only, scope-bound, expiring and integrity-protected;
- uses one persistent global optimistic lock;
- fails closed when expired, revoked, tampered, non-finite or lock-mismatched;
- becomes aborted when a partial persistence/audit failure occurs;
- cannot bypass the kill switch or create a second execution path.

Missing correlation evidence is not zero correlation. Sizing blocks on missing or invalid
correlation and uses the smallest risk, volatility, same-symbol, cluster, authority and
absolute-cap capacity.

Phase 9 reports create immutable Phase 10 snapshots. Monthly reports verify snapshot
hashes, retain history and expose net PnL, fees, matched fills and maximum drawdown.

## Phase 11 production audit

`ProductionAudit` verifies:

- compile/runtime execution locks and canonical `ApprovedExecutionRequest`;
- authentication, database-required and sandbox configuration;
- SQLite/PostgreSQL database health and secret-file hygiene;
- exact SHA, clean worktree and canonical checkout `/opt/sharipovai-repo`;
- atomic post-deploy evidence and exact-SHA rollback;
- persistent monthly monitoring;
- responsive, injection-safe and security-header-protected dashboard;
- first-campaign machine launch gate;
- Phase 9–11 crash contracts in mandatory CI;
- finite Testnet ceiling at or below 50 USDT.

The deterministic audit SHA excludes timestamps and host metadata. Identical audited
state produces identical evidence.

Read-only admin endpoints:

```text
GET /api/production/phase11/audit
GET /api/production/phase11/overview
GET /api/campaigns/phase10/activations
GET /api/performance/phase10/overview
```

Sensitive Phase 9–11 routes are authorized before request body parsing.

## Phase 12 evidence-driven self-learning and validation

Phase 12 closes the research learning loop without creating execution authority:

```text
verified Paper/Testnet outcome
  -> immutable outcome attribution
  -> persistent agent metrics
  -> evidence-gated research challenger
  -> canonical Experiment Registry
  -> walk-forward / benchmark / data-validation checks
  -> automatic Paper research champion
  -> separate manual promotion decision for every execution stage
```

`OutcomeAttributionService` accepts only verified Paper or authenticated Testnet
evidence. Synthetic, mock, demo, fixture, non-finite and conflicting evidence is
blocked. PnL and drawdown attribution must reconcile exactly to the settled outcome.

`ResearchChallengerService` creates persistent challenger experiments with commit SHA,
manifest hash, strategy configuration and learning evidence. Automatic promotion is
restricted to **Paper research champion**. Automatic execution promotion is forbidden.
Testnet, scaling and every future Mainnet decision remain separate evidence-gated manual
decisions.

`Phase12FillValidationService` combines expected-versus-actual Paper validation with
Paper-versus-Testnet shadow comparison. It measures latency, price/slippage, fees, fill
ratio, missing fills and partial fills, stores an immutable SHA-256 report in the
Experiment Registry and never performs auto-promotion. The canonical final report and
operator CLI remain required for campaign promotion.

The self-learning supervisor is restart-safe, bounded and observable. It scans canonical
Paper settlements, processes each immutable outcome once and persists status in
`ProjectDatabase`. Its failure degrades learning only; it cannot submit an order, change
capital, alter credentials, release the kill switch or modify runtime flags.

Phase 12 pre-merge and deployment contracts:

```bash
python scripts/phase12_premerge_checklist.py --expected-sha "$(git rev-parse HEAD)"
export SHARIPOVAI_EXPECTED_SHA='<40-character-reviewed-sha>'
sudo -E APP_DIR=/opt/sharipovai-repo bash deploy/vps/phase12_release_preflight.sh
sudo APP_DIR=/opt/sharipovai-repo bash deploy/vps/update_from_main.sh
sudo -E APP_DIR=/opt/sharipovai-repo bash deploy/vps/phase12_post_deploy_verify.sh
```

Rollback requires the exact reviewed current SHA, an ancestor target SHA and the explicit
Phase 12 confirmation. The wrapper delegates to the proven Phase 11 rollback, then
re-verifies exact SHA, container provenance, health and production-safe locks.

## Dashboard

Campaign Operations, Live Monitoring, Campaign Analysis, Scaling and Production panels
use:

- safe `textContent` and `replaceChildren`, never `innerHTML` or `eval`;
- `AbortController`, request timeouts and exponential backoff;
- offline/hidden-tab pause and truthful unavailable states;
- dark/light/system themes and persisted preference;
- responsive mobile grids, 44 px controls, focus visibility and reduced motion;
- `nosniff`, clickjacking protection, referrer/permissions isolation and HTTPS HSTS.

The dashboard cannot submit a raw order or change the Mainnet compile lock.

## Operator CLI and operator control plane

The operator CLI is `scripts/testnet_campaignctl.py`:

```bash
python scripts/testnet_campaignctl.py snapshot
python scripts/testnet_campaignctl.py plan \
  --experiment-id '<approved-experiment>' \
  --confirmation I_APPROVE_BOUNDED_TESTNET_SHADOW_CAMPAIGN
```

Write operations require action-specific confirmations. The operator control plane
cannot install credentials, alter deployment flags, enable Mainnet or blind-retry an
ambiguous order.

## CI cleanroom and crash suite

Every GitHub Actions pytest process runs the fail-closed CI cleanroom before imports.
It verifies safe flags, rejects production exchange state, removes only explicit
workspace or `/tmp` state and retains JSON evidence.

`Phase 11 Hardening` runs dependency audit, compilation, immutable evidence tests,
concurrent activation, partial write failure, non-finite inputs, database/network
failure, dashboard security, canonical deployment paths, rollback and first-campaign
launch contracts.

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
python -m pytest -q --tb=short
```

## Production deployment

```bash
cd /opt/sharipovai-repo
export SHARIPOVAI_EXPECTED_SHA='<40-character-reviewed-sha>'
sudo -E APP_DIR=/opt/sharipovai-repo bash deploy/vps/phase12_release_preflight.sh
sudo APP_DIR=/opt/sharipovai-repo bash deploy/vps/update_from_main.sh
sudo -E APP_DIR=/opt/sharipovai-repo bash deploy/vps/phase12_post_deploy_verify.sh
sudo APP_DIR=/opt/sharipovai-repo bash deploy/vps/install_phase10_monthly_monitor.sh
```

Pre-deploy audit does not authorize a campaign. After the finite Testnet runtime is
explicitly deployed, run the read-only checklist:

```bash
docker exec -e SHARIPOVAI_EXPECTED_SHA="$SHARIPOVAI_EXPECTED_SHA" sharipovai \
  python scripts/phase11_first_campaign_checklist.py \
  --experiment-id '<approved-experiment-id>' \
  --expected-sha "$SHARIPOVAI_EXPECTED_SHA"
```

Proceed only with `ready=true` and `failed_checks=[]`.

Exact-SHA rollback:

```bash
export SHARIPOVAI_ROLLBACK_SHA='<reviewed-ancestor-sha>'
sudo -E APP_DIR=/opt/sharipovai-repo bash deploy/vps/phase11_rollback.sh \
  I_APPROVE_PHASE11_EXACT_SHA_ROLLBACK
```

See `docs/phase11-production-launch.md` for the complete state machine and abort plan.

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
- Testnet keys must not have withdrawal or transfer permissions.
- Never commit `.env`, database files, state snapshots or credentials.
- Keep the kill switch active outside the explicitly authorized finite Testnet window.
