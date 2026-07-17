# SharipovAI OS

SharipovAI is a safety-first AI trading operating system built around verified market evidence, deterministic risk controls, persistent experiments, realistic Paper execution, walk-forward research and bounded Testnet shadow campaigns.

> **Production state:** Mainnet execution is compiled out. Production boots with the execution kill switch engaged and every Testnet write flag disabled. A campaign is not complete until it contains at least 20 campaign-bound authenticated private fills, actual fees, clean reconciliation and a canonical final report.

SharipovAI does not guarantee profit. Results are measured after spread, fees, slippage, nonlinear impact, funding, drawdown and execution failures.

## Documentation

- Binding policy: [`CONSTITUTION.md`](CONSTITUTION.md)
- Phase 7 production runbook: [`docs/phase7-production-testnet-campaign.md`](docs/phase7-production-testnet-campaign.md)
- First bounded Testnet runbook: [`docs/first-real-testnet-campaign.md`](docs/first-real-testnet-campaign.md)
- Phase 6 operations notes: [`docs/phase6-legacy-and-campaign-operations.md`](docs/phase6-legacy-and-campaign-operations.md)

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

Storage, validation, scheduling, campaign orchestration, experiment registries, monitoring, transport, idempotency and backtesting are infrastructure.

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
  -> bounded Testnet shadow plan
  -> ApprovedExecutionRequest
  -> durable idempotency reservation
  -> Testnet adapter
  -> authenticated private order/execution evidence
  -> reconciliation and Runtime Fill Harvester
  -> immutable final promotion report
  -> manual decision
```

There is one canonical exchange-write adapter. Dashboard pages, Telegram, schedulers, strategies, CLIs, agents and LLM output cannot bypass it.

## Safety invariants

- Mainnet is unavailable in the compiled runtime.
- The execution kill switch is the permanent production-safe default.
- Testnet is bounded to 10–25 USDT per accepted campaign order.
- Every intent has a deterministic identity and durable reservation.
- Ambiguous outcomes remain unresolved and are never retried blindly.
- Private order and execution streams must be authenticated and fresh.
- Campaign completion requires 20+ matched fills and zero orphan, duplicate, unmatched, conflicting or unresolved evidence.
- Actual private execution fees are mandatory evidence.
- Promotion records and manual decisions never change runtime flags.
- Secrets and runtime state stay outside Git, logs, metrics and reports.
- Failed, missing, queued or skipped CI is never treated as green.

## Phase 7

Phase 7 adds production supervision around the existing canonical services. It does not add a second campaign launcher or execution path.

Delivered:

- immutable-target VPS preflight before backup and code replacement;
- current SQLite header and integrity validation;
- minimum free-disk and secret-file permission checks;
- non-root Docker build verification, init handling, graceful shutdown, bounded logs, dropped capabilities and healthchecks;
- permanent production-safe Compose and separate bounded-Testnet overlay;
- fail-closed env validation that rejects Mainnet credentials and notional above 25 USDT;
- verified backup, health/database smoke checks and automatic restoration of production-safe Compose;
- finite/resumable first-campaign runner with persistent JSON/JSONL evidence;
- persistent deduplicated critical alerts with automatic resolution history;
- optional sanitized HTTPS webhook and Telegram delivery;
- three-second responsive Campaign Dashboard refresh;
- actual campaign-bound private fill timeline and fee totals;
- atomic operational export after the canonical final report exists.

The Phase 7 monitor and alerting layer are read-only. They cannot install credentials, change execution flags, release the kill switch, modify capital, submit an order or enable Mainnet.

## Production-safe deployment files

| File | Purpose |
| --- | --- |
| `Dockerfile` | non-root image, build checks and container health contract |
| `deploy/vps/docker-compose.yml` | permanent production-safe runtime; kill switch on |
| `deploy/vps/docker-compose.testnet-campaign.yml` | explicit temporary bounded-Testnet override |
| `deploy/vps/.env.vps.example` | production config without execution credentials |
| `deploy/vps/.env.testnet-campaign.example` | isolated Testnet release/credential template |
| `deploy/vps/phase7_preflight.sh` | disk, Docker, Compose, lock and SQLite validation |
| `deploy/vps/validate_runtime_env.py` | fail-closed production/Testnet env validation |
| `deploy/vps/smoke_check.sh` | rendered flags, HTTP, container and database health |
| `deploy/vps/update_from_main.sh` | backup-first production update and rollback |
| `deploy/vps/testnet_campaign_deploy.sh` | exact-confirmation Testnet runtime transition |
| `deploy/vps/testnet_campaign_stop.sh` | exact-confirmation restoration of production locks |

Production verification:

```bash
python3 deploy/vps/validate_runtime_env.py \
  --env-file deploy/vps/.env.vps \
  --mode production
sudo bash deploy/vps/smoke_check.sh production
```

## Bounded Testnet runtime window

Permanent production settings remain in `.env.vps`. Do not edit those locks for a campaign.

Create the separate ignored overlay:

```bash
cd deploy/vps
cp .env.testnet-campaign.example .env.testnet-campaign
chmod 600 .env.testnet-campaign
```

Validate and enter the bounded window:

```bash
python3 validate_runtime_env.py \
  --env-file .env.vps \
  --env-file .env.testnet-campaign \
  --mode testnet-campaign

sudo bash testnet_campaign_deploy.sh \
  I_APPROVE_BOUNDED_TESTNET_RUNTIME_DEPLOYMENT
```

Restore production-safe locks after completion, failure, timeout or abort:

```bash
sudo bash testnet_campaign_stop.sh \
  I_APPROVE_RESTORE_PRODUCTION_KILL_SWITCH
```

Mainnet remains unavailable in both modes.

## First real Testnet campaign

`scripts/first_testnet_campaign.py` is a finite operator runner over canonical campaign services. It requires distinct exact confirmations, has hard cycle/time limits, may resume only the same campaign, and writes an append-only evidence bundle.

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

The runner exits `0` only when `real_fill_evidence_confirmed=true`; incomplete or blocked outcomes exit `2` and retain evidence.

## Campaign Operations

The **Кампании** page combines:

- exact readiness gates;
- the single active campaign authorization;
- matched-fill progress and remaining fills;
- actual authenticated private fills and execution identities;
- actual private fees;
- orphan, duplicate, unresolved and unmatched blockers;
- persistent critical alerts and manual re-evaluation;
- private-stream and monitor heartbeat;
- immutable final-report readiness and export path;
- separate report-bound manual decisions;
- responsive tablet/mobile layouts and visibility-aware polling.

Key admin routes:

| Route | Purpose |
| --- | --- |
| `/api/campaigns/operations` | Canonical operations snapshot |
| `/api/campaigns/first-testnet/plan` | First-campaign readiness gates |
| `/api/campaigns/first-testnet/start` | Existing gated campaign launcher |
| `/api/campaigns/{id}/run` | Canonical campaign cycle |
| `/api/campaigns/{id}/promotion-report` | Canonical final report |
| `/api/campaigns/{id}/decision` | Report-bound manual decision |
| `/api/campaigns/phase7/monitor` | Live read-only Phase 7 snapshot |
| `/api/campaigns/phase7/fills` | Campaign-bound actual private fills |
| `/api/campaigns/phase7/report` | Final report and export evidence |
| `/api/campaigns/phase7/alerts` | Persistent critical-alert state |
| `/api/campaigns/phase7/alerts/refresh` | Immediate read-only alert evaluation |

Administrative routes require authentication. No route exposes a raw order primitive.

## Critical alerting

`CampaignCriticalAlertService` persists deduplicated alerts and resolution history in `ProjectDatabase`.

Critical signals:

- multiple active campaigns;
- kill switch engaged during an active campaign;
- failed startup/execution reconciliation;
- stale private order/execution stream;
- stale Phase 7 heartbeat;
- blocked campaign;
- orphan, duplicate, unresolved, reconciliation or notional failure;
- orchestrator errors.

Optional delivery:

```env
CRITICAL_ALERT_MONITOR_ENABLED=1
CRITICAL_ALERT_MONITOR_SECONDS=15
CRITICAL_ALERT_REPEAT_SECONDS=900
ALERT_DELIVERY_ENABLED=0
ALERT_TELEGRAM_CHAT_ID=
ALERT_WEBHOOK_URL=
```

External delivery may fail; persisted canonical alert evidence must not disappear.

## Main components

| Component | Responsibility |
| --- | --- |
| `dashboard/` | FastAPI dashboard and protected APIs |
| `dashboard/phase7_campaign_api.py` | Phase 7 monitor, alert, fill and report projections |
| `dashboard/static/web2/campaign_monitor_v38.js` | Three-second responsive Campaign UI |
| `campaigns/core.py` | Bounded campaign state machine and final reports |
| `campaigns/operations.py` | Readiness and canonical campaign operations |
| `campaigns/phase7_monitor.py` | Heartbeat, actual fills and report export |
| `observability/critical_alerts.py` | persistent critical alert lifecycle and delivery |
| `scripts/testnet_campaignctl.py` | canonical operator control plane |
| `scripts/first_testnet_campaign.py` | finite real-evidence campaign runner |
| `exchange_connector/` | Reference data, execution contract and private evidence |
| `validation/runtime_fill_harvester.py` | Paper/Testnet divergence from actual fills |
| `experiments/` | Immutable research and promotion evidence |
| `risk_engine/` | Hard limits and bounded soft-risk scaling |
| `storage/` | Canonical shared database and evidence ledger |

## Development

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
python -m pytest tests/test_phase7_campaign_monitor.py tests/test_phase7_monitor_ui.py tests/test_phase7_deployment_stability.py -q --tb=short
python -m pytest tests/test_phase7_critical_alerts.py tests/test_phase7_campaign_runtime_deployment.py tests/test_first_testnet_campaign_runner.py tests/test_phase7_alert_ui.py -q --tb=short
python -m pytest -q --tb=short
```

Merge only after complete factual green CI and retained artifacts.

## Security

- Rotate any key exposed in chat, screenshots or logs.
- Separate read-only, Testnet and future Mainnet credentials.
- Disable withdrawal and transfer permissions.
- Never commit environment files, databases, state snapshots or credentials.
- Keep `.env.vps` and `.env.testnet-campaign` mode `0600`.
- Keep the kill switch active outside an explicitly authorized bounded Testnet campaign.
- Never fabricate or manually repair financial evidence.
