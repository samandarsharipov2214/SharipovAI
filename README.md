# SharipovAI OS

SharipovAI is a safety-first AI trading operating system for verified market evidence, deterministic risk controls, realistic Paper execution, walk-forward research and bounded Testnet campaigns.

> **Runtime state:** Mainnet execution is compiled out. Production boots with the kill switch enabled and every Testnet write flag disabled. A real campaign is successful only when authenticated private fills and fees satisfy the immutable completion gates.

SharipovAI does not guarantee profit. Performance must be measured after spread, fees, slippage, impact, funding, drawdown and execution failures.

- Binding policy: [`CONSTITUTION.md`](CONSTITUTION.md)
- Phase 7 production runbook: [`docs/phase7-production-readiness.md`](docs/phase7-production-readiness.md)
- First real Testnet campaign: [`docs/first-real-testnet-campaign.md`](docs/first-real-testnet-campaign.md)

## Safety invariants

- `MAINNET_EXECUTION_COMPILED=False` cannot be overridden by configuration, UI, Telegram, agents, experiments or approvals.
- Production default is `EXECUTION_KILL_SWITCH=1` with all Testnet execution flags off.
- No dashboard, scheduler, strategy, CLI or LLM output can submit a raw order.
- The only exchange write entry is `BybitExecutionClient.execute(ApprovedExecutionRequest)`.
- Every intent is durably reserved with deterministic `orderLinkId` before network submission.
- Ambiguous outcomes remain unresolved and are never blind-retried.
- Testnet requires authenticated private `order` and `execution` topics plus restart-safe reconciliation.
- One global non-terminal campaign is allowed.
- Every accepted campaign order is bounded to 10–25 USDT.
- Completion requires 20+ matched Paper/Testnet fills, actual fees and zero unmatched, orphan, duplicate or unresolved evidence.
- Secrets and runtime state stay outside Git, logs, metrics and report payloads.
- Partial, skipped, queued or failed CI is not approval.

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
  -> active bounded campaign authorization
  -> actual Bybit fee/instrument validation
  -> ApprovedExecutionRequest
  -> durable idempotency reservation
  -> Bybit Testnet submission
  -> private order + execution evidence
  -> reconciliation
  -> Runtime Fill Harvester
  -> immutable final report
  -> separate manual decision
```

## Production deployment model

Phase 7 separates permanent production configuration from temporary Testnet authorization:

```text
deploy/vps/.env.vps                   # production-safe, kill switch on
deploy/vps/.env.testnet-campaign      # ignored secret overlay for one authorized window
```

Key deployment files:

| File | Purpose |
| --- | --- |
| `Dockerfile` | non-root image, `tini`, healthcheck and build verification |
| `deploy/vps/docker-compose.yml` | hardened production-safe service definition |
| `deploy/vps/docker-compose.testnet-campaign.yml` | explicit bounded Testnet override |
| `deploy/vps/validate_runtime_env.py` | fail-closed merged env validation |
| `deploy/vps/smoke_check.sh` | rendered flags, health and database checks |
| `deploy/vps/update_from_main.sh` | backup, reviewed update and rollback |
| `deploy/vps/testnet_campaign_deploy.sh` | exact-confirmation transition to bounded Testnet |
| `deploy/vps/testnet_campaign_stop.sh` | exact-confirmation restoration of production locks |
| `deploy/vps/recover_corrupt_database_and_deploy.sh` | evidence-preserving SQLite recovery path |

Production validation:

```bash
python3 deploy/vps/validate_runtime_env.py \
  --env-file deploy/vps/.env.vps \
  --mode production
sudo bash deploy/vps/smoke_check.sh production
```

Bounded Testnet validation:

```bash
python3 deploy/vps/validate_runtime_env.py \
  --env-file deploy/vps/.env.vps \
  --env-file deploy/vps/.env.testnet-campaign \
  --mode testnet-campaign
```

## First real Testnet campaign

Enter the finite execution window:

```bash
sudo bash deploy/vps/testnet_campaign_deploy.sh \
  I_APPROVE_BOUNDED_TESTNET_RUNTIME_DEPLOYMENT
```

Run the evidence collector:

```bash
docker exec sharipovai python scripts/first_testnet_campaign.py \
  --experiment-id '<promoted-experiment-id>' \
  --scope BTCUSDT \
  --actor '<authenticated-operator>' \
  --output-dir /var/lib/sharipovai/evidence/testnet-campaigns \
  --start-confirmation I_APPROVE_BOUNDED_TESTNET_SHADOW_CAMPAIGN \
  --cycle-confirmation I_APPROVE_BOUNDED_TESTNET_CAMPAIGN_CYCLE \
  --report-confirmation I_APPROVE_IMMUTABLE_CAMPAIGN_REPORT
```

The runner is fail-closed, finite and resumable. It exits `0` only with `real_fill_evidence_confirmed=true`; all incomplete or blocked outcomes exit `2` and retain evidence.

Restore locks immediately after the run:

```bash
sudo bash deploy/vps/testnet_campaign_stop.sh \
  I_APPROVE_RESTORE_PRODUCTION_KILL_SWITCH
```

## Monitoring and alerting

`CampaignCriticalAlertService` stores deduplicated alerts in the canonical database and optionally delivers sanitized HTTPS webhook or Telegram notices.

Critical signals:

- multiple active campaigns;
- kill switch engaged during an active campaign;
- failed startup/execution reconciliation;
- stale private order/execution stream;
- blocked campaign;
- orphan, duplicate, unresolved, reconciliation or notional failure;
- orchestrator errors.

Configuration:

```env
CRITICAL_ALERT_MONITOR_ENABLED=1
CRITICAL_ALERT_MONITOR_SECONDS=15
CRITICAL_ALERT_REPEAT_SECONDS=900
ALERT_DELIVERY_ENABLED=0
ALERT_TELEGRAM_CHAT_ID=
ALERT_WEBHOOK_URL=
```

Alerts remain persisted when delivery is disabled or unavailable.

## Campaign Operations dashboard

Open `/#campaigns` after admin authentication.

The responsive page provides:

- control-plane health and stale-data indication;
- campaign selection and history;
- matched-fill progress and actual fee totals;
- orphan, duplicate and unresolved counters;
- live critical alerts and manual evaluation;
- release gates and blockers;
- schedule creation, orchestrator tick and campaign cycle;
- final report action and exact launch confirmation helper;
- visibility-aware auto-refresh.

Relevant APIs:

| Route | Purpose |
| --- | --- |
| `/api/campaigns/operations` | complete operations and alerts snapshot |
| `/api/campaigns/alerts` | alert monitor status |
| `/api/campaigns/alerts/tick` | immediate alert evaluation |
| `/api/campaigns/first-testnet/plan` | exact readiness gates |
| `/api/campaigns/first-testnet/start` | gated campaign start |
| `/api/campaigns/orchestrator/tick` | scheduler cycle |
| `/api/campaigns/schedules` | list/create approved schedules |
| `/api/campaigns/{id}/run` | one canonical campaign cycle |
| `/api/campaigns/{id}/promotion-report` | immutable final report |
| `/api/campaigns/{id}/decision` | separate manual decision |

No route exposes a raw order primitive.

## Canonical components

| Component | Responsibility |
| --- | --- |
| `campaigns/core.py` | bounded campaign state machine and immutable reports |
| `campaigns/orchestrator.py` | non-overlapping approved schedules |
| `campaigns/operations.py` | readiness and operational read model |
| `campaigns/decisions.py` | report-bound manual decisions |
| `scripts/testnet_campaignctl.py` | fail-closed operator commands |
| `scripts/first_testnet_campaign.py` | finite real-evidence runner |
| `observability/critical_alerts.py` | persistent campaign-critical alerting |
| `dashboard/campaign_api.py` | authenticated campaign and alert APIs |
| `validation/runtime_fill_harvester.py` | actual Paper/Testnet fill joins |
| `validation/fill_divergence.py` | divergence metrics and policy |
| `exchange_connector/bybit_execution.py` | canonical Testnet execution client |
| `exchange_connector/bybit_order_state.py` | private order lifecycle |
| `exchange_connector/bybit_execution_state.py` | private fills, fees and partial fills |
| `autonomous_trading/startup_reconciliation.py` | restart safety |
| `storage/` | canonical shared database and evidence ledger |
| `experiments/` | immutable research and promotion evidence |
| `trading_core/` | event-driven backtest and benchmarks |
| `risk_engine/` | hard limits and bounded sizing |

## Safe defaults

```env
EXCHANGE_MODE=sandbox
EXCHANGE_BASE_URL=https://api-testnet.bybit.com
EXCHANGE_LIVE_TRADING_ENABLED=0
FEATURE_BYBIT_LIVE_EXECUTION=0
EXECUTION_KILL_SWITCH=1
TESTNET_EXECUTION_ENABLED=0
AUTONOMOUS_TESTNET_ENABLED=0
AUTONOMOUS_TESTNET_BRIDGE_ENABLED=0
FEATURE_BYBIT_TESTNET=0
FEATURE_BYBIT_PRIVATE_ORDER_WS=0
RUNTIME_FILL_HARVESTER_ENABLED=0
SCHEDULED_CAMPAIGN_ORCHESTRATOR_ENABLED=0
PHASE6_TESTNET_RELEASE_GATE=blocked
EXECUTION_MAX_NOTIONAL_USDT=25
SHADOW_TESTNET_MAX_NOTIONAL_USDT=25
CRITICAL_ALERT_MONITOR_ENABLED=1
```

## Development and verification

Python 3.12 is required.

```bash
python -m venv .venv
source .venv/bin/activate  # Windows PowerShell: .venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
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

Merge only after complete factual green CI and retained test artifacts.

## Security

- Rotate any secret exposed in chat, screenshots or logs.
- Separate read-only, Testnet and future Mainnet credentials.
- Disable withdrawal and transfer permissions.
- Keep `.env.vps` and `.env.testnet-campaign` mode `0600` and outside Git.
- Keep the kill switch active outside an explicitly authorized bounded Testnet window.
- Never repair financial evidence manually or fabricate catch-up fills.
