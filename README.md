# SharipovAI OS

SharipovAI is a safety-first AI trading operating system for verified market evidence, deterministic risk, realistic Paper execution and bounded Bybit Testnet campaigns.

> **Production state:** Mainnet execution is compiled out. Production boots with the kill switch engaged. Testnet writes exist only inside an explicitly authorized bounded window. Scaling preparation is evidence-only and cannot alter runtime notional.

## Phase 9

Phase 9 adds detailed campaign results, risk metrics, fail-closed notional scaling preparation, advanced dashboard/Telegram alert projection and deployment verification.

Delivered:

- realized gross/net PnL and actual fees;
- closed-trade reconstruction from authenticated private fills;
- win rate, profit factor, maximum drawdown and closed notional;
- Paper/Testnet price and fee divergence retention;
- immutable Phase 9 campaign reports;
- step-by-step scaling gates across multiple campaigns;
- a bounded next-step proposal from 25 to 37.5 USDT, capped at 50 USDT;
- mandatory manual scaling review;
- dashboard scaling panel and critical alert projection;
- Telegram/HTTPS delivery through the persistent Phase 7 alert authority;
- structured logging defaults and atomic post-deploy verification;
- Mainnet remains unavailable.

## Documentation

- [`CONSTITUTION.md`](CONSTITUTION.md)
- [`docs/phase8-campaign-launch-and-analysis.md`](docs/phase8-campaign-launch-and-analysis.md)
- [`docs/phase9-results-scaling-monitoring.md`](docs/phase9-results-scaling-monitoring.md)

## Phase 9 API

```text
POST /api/campaigns/phase9/report/{campaign_id}
GET  /api/campaigns/phase9/report/{campaign_id}
GET  /api/campaigns/phase9/reports
POST /api/campaigns/phase9/scaling-plan
GET  /api/campaigns/phase9/scaling-plans
```

All routes are admin-only. No endpoint changes execution flags or order notional.

## Scaling preparation

```bash
python scripts/phase9_scaling_plan.py \
  --campaign-id '<campaign-1>' \
  --campaign-id '<campaign-2>' \
  --actor '<authenticated-operator>' \
  --reason 'two clean bounded campaigns' \
  --output /var/lib/sharipovai/campaign_reports/phase9-scaling-plan.json
```

Exit code `0` means eligible for manual scaling review. Exit code `2` means blocked. Neither result changes runtime state.

## Production verification

```bash
sudo bash deploy/vps/phase9_post_deploy_verify.sh
```

The verifier checks Compose rendering, Python compilation, HTTP health and SQLite integrity. It writes an atomic JSON report and fails closed.

## Alert delivery

```env
CRITICAL_ALERT_MONITOR_ENABLED=1
ALERT_DELIVERY_ENABLED=1
ALERT_TELEGRAM_CHAT_ID=<chat-id>
ALERT_WEBHOOK_URL=https://<trusted-endpoint>
```

Critical drawdown and failed evidence gates are Telegram-eligible. Blocked scaling plans are dashboard/webhook warnings. Delivery failure never erases canonical alert evidence.

## Verification

```bash
python -m pip install -r requirements-dev.txt
python -m pip check
python -m compileall -q .
python -m pytest tests/test_phase9_results_and_scaling.py tests/test_phase9_dashboard_contract.py tests/test_phase9_deployment_contract.py -q --tb=short
python -m pytest -q --tb=short
```

## Truth rule

A campaign, PnL result or scaling eligibility is never fabricated. Only campaign-bound authenticated private Testnet fills, actual fees, clean reconciliation and persisted reports are evidence. A passing scaling plan is not approval and cannot enable Mainnet.
