# SharipovAI OS

SharipovAI is a safety-first AI trading operating system for verified market evidence, deterministic risk, realistic Paper execution and bounded Bybit Testnet campaigns.

> **Production state:** Mainnet execution is compiled out. Production boots with the kill switch engaged. Testnet writes exist only inside explicitly authorized finite windows. Phase 10 scaling is expiring, scope-bound and capped at 50 USDT.

## Phase 10

Phase 10 adds controlled Testnet notional scaling, persistent long-term performance tracking, correlation-aware capital allocation and a live Scaling & Performance dashboard.

Delivered:

- exact-confirmation activation from an eligible Phase 9 scaling plan;
- finite Testnet-only scaling authority with scope, TTL, authority hash and revoke path;
- validation before any request may use the increased notional ceiling;
- no second exchange-write path and no kill-switch override;
- persistent performance snapshots and monthly reports;
- monthly net PnL, actual fees, matched fills and maximum drawdown;
- critical expired-authority and drawdown alerts;
- correlation-cluster-aware position sizing;
- volatility, stop-distance, equity and scaling-ceiling limits;
- responsive Scaling Dashboard and Performance Overview;
- Mainnet remains unavailable.

## Documentation

- [`CONSTITUTION.md`](CONSTITUTION.md)
- [`docs/phase9-results-scaling-monitoring.md`](docs/phase9-results-scaling-monitoring.md)
- [`docs/phase10-controlled-scaling-performance.md`](docs/phase10-controlled-scaling-performance.md)

## Phase 10 API

```text
POST /api/campaigns/phase10/activate/{plan_id}
POST /api/campaigns/phase10/revoke/{activation_id}
GET  /api/campaigns/phase10/activations
GET  /api/performance/phase10/overview
POST /api/risk/phase10/size
```

All routes are admin-only. Activation does not place an order. Existing canonical execution code must validate the activation ID, scope, expiry and requested notional before execution.

## Controlled scaling

```bash
curl -X POST \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  "https://<dashboard>/api/campaigns/phase10/activate/<plan-id>" \
  -d '{
    "actor": "<authenticated-owner>",
    "scope": "BTCUSDT",
    "confirmation": "I_APPROVE_CONTROLLED_TESTNET_NOTIONAL_SCALING"
  }'
```

Default policy permits one controlled step, such as 25 to 37.5 USDT, never exceeding 1.5x or 50 USDT. Authority expires after 24 hours by default.

Revoke after completion, failure, stale evidence, drawdown breach or rollback:

```bash
curl -X POST \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  "https://<dashboard>/api/campaigns/phase10/revoke/<activation-id>" \
  -d '{"actor":"<authenticated-owner>","reason":"campaign window closed"}'
```

## Monthly performance report

```bash
python scripts/phase10_monthly_report.py \
  --month 2026-07 \
  --output /var/lib/sharipovai/performance/2026-07.json
```

Exit code `2` means maximum monthly drawdown exceeded policy. The report remains canonical evidence.

## Correlation-aware sizing

The risk engine uses the smallest of:

- risk-budget notional derived from equity and stop distance;
- volatility-adjusted position size;
- maximum position fraction;
- remaining correlated-cluster capacity;
- active scaling authority ceiling;
- absolute 50 USDT Testnet ceiling.

Invalid equity, stop distance, expired authority or exhausted cluster capacity fails closed.

## Verification

```bash
python -m pip install -r requirements-dev.txt
python -m pip check
python -m compileall -q .
python -m pytest tests/test_phase10_controlled_scaling.py tests/test_phase10_capital_engine.py tests/test_phase10_monitoring_dashboard_contract.py -q --tb=short
python -m pytest -q --tb=short
```

## Truth rule

Scaling activation is not proof of profitable execution. Only campaign-bound authenticated private Testnet fills, actual fees, clean reconciliation and persisted reports are evidence. SharipovAI does not promise profit and cannot enable Mainnet through configuration, dashboard, Telegram, LLM output or a scaling authority record.
