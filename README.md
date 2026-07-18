# SharipovAI OS

SharipovAI is a safety-first AI trading operating system for verified market evidence, deterministic risk, realistic Paper execution and bounded Bybit Testnet campaigns.

> **Production state:** Mainnet execution is compiled out. Production boots with the kill switch engaged. Testnet writes exist only inside an explicitly authorized bounded window. Phase 8 performs post-campaign analysis only and cannot change execution flags, credentials or order notional.

## Phase 7 foundation

Canonical audited production concepts retained from Phase 7:

- historical_data;
- execution_status;
- fill_divergence;
- experiment_results_ui;
- experiment_comparison_ui;
- private streams default off;
- CI cleanroom;
- operator CLI;
- 10–25 USDT bounded Testnet notional;
- at least 20 matched fills;
- zero orphan, duplicate or unresolved execution identities;
- authenticated private execution evidence;
- final promotion report;
- manual decisions only;
- Mainnet execution compiled out.

## Phase 8

Phase 8 adds canonical post-campaign analysis over campaign-bound authenticated private fills.

Delivered:

- FIFO realized gross and net PnL;
- turnover, actual fees and open inventory;
- Paper/Testnet price and fee divergence;
- deterministic fail-closed analysis gates;
- a recommendation that cannot automatically promote or scale execution;
- admin-only analysis API and CLI report generation;
- responsive live Campaign Analysis dashboard panel;
- persistent Phase 7 Telegram/HTTPS critical alert routing retained as the authority;
- focused analytics, API, dashboard, CLI and policy contract tests;
- Mainnet remains unavailable.

## Documentation

- [`CONSTITUTION.md`](CONSTITUTION.md)
- [`docs/phase7-production-testnet-campaign.md`](docs/phase7-production-testnet-campaign.md)
- [`docs/first-real-testnet-campaign.md`](docs/first-real-testnet-campaign.md)
- [`docs/phase8-campaign-launch-and-analysis.md`](docs/phase8-campaign-launch-and-analysis.md)

## Phase 8 API

```text
POST /api/campaigns/phase8/analyze/{campaign_id}
GET  /api/campaigns/phase8/analysis/{campaign_id}
GET  /api/campaigns/phase8/analyses
```

All routes are admin-only. No Phase 8 route places orders or changes runtime execution authority.

## Verification

```bash
python -m pip install -r requirements-dev.txt
python -m pip check
python -m compileall -q .
python -m pytest tests/test_phase8_campaign_analysis.py tests/test_phase8_dashboard_contract.py -q --tb=short
python -m pytest -q --tb=short
```

## Truth rule

A campaign, fill, fee, PnL result or recommendation is never fabricated. Only campaign-bound authenticated private Testnet evidence and persisted canonical reports may be presented as fact. A successful analysis is not permission to scale, deploy or enable Mainnet.
