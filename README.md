# SharipovAI OS

SharipovAI is a safety-first AI trading operating system built around verified
market evidence, deterministic risk controls, persistent experiments, realistic
Paper execution, walk-forward research and bounded Testnet shadow campaigns.

> **Production state:** Mainnet execution is compiled out. Testnet remains
> fail-closed unless the deployed runtime proves every readiness gate. A campaign
> is not complete until it contains at least 20 campaign-bound authenticated
> private fills, actual fees, clean reconciliation and a canonical final report.

SharipovAI does not guarantee profit. Results are measured after spread, fees,
slippage, nonlinear impact, funding, drawdown and execution failures.

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

Storage, validation, scheduling, campaign orchestration, experiment registries,
monitoring, transport, idempotency and backtesting are infrastructure.

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

There is one canonical exchange-write adapter. Dashboard pages, Telegram,
schedulers, strategies, CLIs, agents and LLM output cannot bypass it.

## Safety invariants

- Mainnet is unavailable in the compiled runtime.
- The execution kill switch is the safe default.
- Testnet is bounded to 10–25 USDT per accepted campaign order.
- Every intent has a deterministic identity and durable reservation.
- Ambiguous outcomes remain unresolved and are never retried blindly.
- Private order and execution streams must be authenticated and fresh.
- Campaign completion requires 20+ matched fills and zero orphan, duplicate,
  unmatched, conflicting or unresolved evidence.
- Actual private execution fees are mandatory evidence.
- Promotion records and manual decisions never change runtime flags.
- Secrets and runtime state stay outside Git, logs, metrics and reports.
- Failed, missing, queued or skipped CI is never treated as green.

## Phase 7

Phase 7 adds production supervision around the existing canonical services. It
does not add a second campaign launcher or execution path.

Delivered:

- target-commit VPS preflight before backup and code replacement;
- current SQLite header and integrity validation;
- minimum free-disk and secret-file permission checks;
- verified backup and rollback preservation;
- Docker init handling, graceful shutdown, bounded logs and faster health checks;
- persistent campaign monitor state;
- three-second Campaign Dashboard refresh;
- actual campaign-bound private fill timeline;
- actual fee totals, stream state, heartbeat and integrity alerts;
- atomic operational export after the canonical final report exists.

The Phase 7 monitor is read-only. It cannot install credentials, change execution
flags, release the kill switch, modify capital, submit an order or enable Mainnet.

## Campaign Operations

The **Кампании** page combines:

- exact readiness gates;
- the single active campaign authorization;
- matched-fill progress and remaining fills;
- actual authenticated private fills and execution identities;
- actual private fees;
- orphan, duplicate, unresolved and unmatched alerts;
- private-stream and monitor heartbeat;
- immutable final-report readiness and export path;
- separate report-bound manual decisions.

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

Administrative routes require authentication. No route exposes a raw order
primitive.

## Main components

| Component | Responsibility |
| --- | --- |
| `dashboard/` | FastAPI dashboard and protected APIs |
| `dashboard/phase7_campaign_api.py` | Phase 7 monitor, fill and report projections |
| `dashboard/static/web2/campaign_monitor_v38.js` | Three-second read-only Campaign UI |
| `campaigns/core.py` | Bounded campaign state machine and final reports |
| `campaigns/operations.py` | Readiness and canonical campaign operations |
| `campaigns/phase7_monitor.py` | Heartbeat, alerts, actual fills and report export |
| `exchange_connector/` | Reference data, execution contract and private evidence |
| `validation/runtime_fill_harvester.py` | Paper/Testnet divergence from actual fills |
| `experiments/` | Immutable research and promotion evidence |
| `risk_engine/` | Hard limits and bounded soft-risk scaling |
| `storage/` | Canonical shared database and evidence ledger |
| `deploy/vps/phase7_preflight.sh` | VPS disk, Compose, safety and SQLite preflight |
| `deploy/vps/update_from_main.sh` | Backup-first deployment with rollback |

## Deployment stability

The VPS updater performs:

```text
fetch immutable target
  -> run target preflight
  -> create verified backup
  -> check out exact target
  -> render and validate Compose
  -> build candidate
  -> replace services
  -> verify local and container health
  -> rollback on any failure
```

Production Compose uses an init process, graceful stop periods, bounded JSON logs,
persistent application/Caddy volumes and a memory-backed temporary directory.

## Operator control

`scripts/testnet_campaignctl.py` is the canonical CLI for snapshot, readiness,
launch, cycle, report and manual decision operations. Every mutation is protected
by a distinct exact confirmation and routes through existing campaign services.
The CLI cannot install credentials, change flags, deploy code or enable Mainnet.

See the Phase 7 runbook for the complete production sequence and truth rules.

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
python -m pytest -q --tb=short
```

Merge only after complete factual green CI and retained artifacts.

## Security

- Rotate any key exposed in chat, screenshots or logs.
- Separate read-only, Testnet and future Mainnet credentials.
- Disable withdrawal and transfer permissions.
- Never commit environment files, databases, state snapshots or credentials.
- Keep the kill switch active outside an explicitly authorized bounded Testnet campaign.
