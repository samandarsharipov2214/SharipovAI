# Phase 10 — Controlled Scaling and Long-Term Performance

Phase 10 converts a clean Phase 9 scaling proposal into an expiring, Testnet-only authority record. It does not introduce a second order path and does not enable Mainnet.

## Preconditions

1. Phase 9 plan status is `eligible_for_manual_scaling_review`.
2. All Phase 9 gates pass.
3. At least two campaign IDs are attached.
4. Proposed notional is greater than the previous notional and no more than 1.5x.
5. Proposed notional does not exceed 50 USDT.
6. Maximum campaign drawdown is no more than 250 bps.
7. Owner supplies the exact confirmation `I_APPROVE_CONTROLLED_TESTNET_NOTIONAL_SCALING`.

## Activation

```bash
curl -X POST \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  "https://<dashboard>/api/campaigns/phase10/activate/<plan-id>" \
  -d '{"actor":"<owner>","scope":"BTCUSDT","confirmation":"I_APPROVE_CONTROLLED_TESTNET_NOTIONAL_SCALING"}'
```

The returned authority is finite, scope-bound, Testnet-only and defaults to a 24-hour TTL. Execution code must validate it before accepting a notional above the production baseline.

## Revocation

```bash
curl -X POST \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  "https://<dashboard>/api/campaigns/phase10/revoke/<activation-id>" \
  -d '{"actor":"<owner>","reason":"campaign window closed"}'
```

Revoke immediately after campaign completion, failure, reconciliation ambiguity, stale private streams, drawdown breach or deployment rollback.

## Capital engine

The capital engine derives a bounded notional from:

- account equity;
- stop distance;
- realized volatility;
- per-position limit;
- correlation-cluster exposure;
- the active scaling ceiling.

The smallest limit wins. A missing or invalid equity/stop fails closed.

## Monthly reports

```bash
python scripts/phase10_monthly_report.py \
  --month 2026-07 \
  --output /var/lib/sharipovai/performance/2026-07.json
```

Exit code `2` means the monthly drawdown limit was exceeded. The report remains persisted even when the alert gate fails.

## Alerts

Critical:

- expired active scaling authority;
- monthly drawdown above 250 bps.

Warning:

- negative monthly net PnL;
- monthly report without matched fills.

Telegram and webhook delivery remain projections into the existing persistent alert authority. Delivery is not execution approval.

## Verification

```bash
python -m compileall -q .
python -m pytest tests/test_phase10_controlled_scaling.py tests/test_phase10_capital_engine.py tests/test_phase10_monitoring_dashboard_contract.py -q --tb=short
python -m pytest -q --tb=short
```
