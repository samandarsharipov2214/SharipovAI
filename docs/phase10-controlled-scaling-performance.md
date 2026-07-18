# Phase 10 — Controlled Scaling and Long-Term Performance

## Scope

Phase 10 authorizes one bounded Testnet notional increase after successful campaign evidence. It does not submit an order, alter runtime flags, disable the kill switch, enable a private stream, or enable Mainnet.

## Authority lifecycle

A scaling authority requires:

- a Phase 9 plan with status `eligible_for_manual_scaling_review`;
- no failed or non-passing gates;
- at least two distinct approved campaigns;
- finite current and proposed notionals;
- a proposed notional greater than the current notional and no more than `1.5x`;
- an absolute hard ceiling of `50 USDT`;
- maximum drawdown within policy;
- exact confirmation `I_APPROVE_CONTROLLED_TESTNET_NOTIONAL_SCALING`;
- a valid exchange-symbol scope;
- no other valid global authority.

The authority is persisted with:

- a canonical SHA-256 authority hash;
- a global optimistic-lock record;
- a finite expiration time;
- explicit `testnet` environment;
- `single_canonical_execution_path=true`;
- `kill_switch_override=false`;
- `mainnet_enabled=false`.

Every use must call `validate_authority()` immediately before the canonical approved execution path. Missing, expired, revoked, tampered, non-finite or lock-mismatched evidence fails closed.

## Correlation-aware capital sizing

`CorrelationAwareCapitalEngine` uses the smallest safe value across:

1. risk-budget notional;
2. volatility-adjusted notional;
3. remaining same-symbol position capacity;
4. remaining correlated-cluster capacity;
5. active scaling ceiling;
6. the absolute 50 USDT Testnet ceiling.

Missing correlation data for any open position is not interpreted as zero correlation. It blocks sizing. Correlations outside `[-1, 1]`, invalid positions and non-finite values also block sizing.

## Persistent performance evidence

A Phase 9 report creates an idempotent Phase 10 performance snapshot using the stable Phase 8 analysis timestamp. Snapshots contain an evidence SHA-256 and are immutable by identity.

Monthly reports:

- use UTC `YYYY-MM` periods;
- verify every source snapshot hash;
- deduplicate exact snapshot IDs;
- reject conflicting duplicate identities;
- retain previous reports when evidence changes;
- store net PnL, fees, matched fills and maximum drawdown;
- raise a drawdown alert above policy;
- return warning exit code `3` when no matched-fill evidence exists;
- return failure exit code `2` on a drawdown breach.

## Operations

Install the persistent monthly timer:

```bash
sudo bash deploy/vps/install_phase10_monthly_monitor.sh
```

Verify it:

```bash
systemctl status sharipovai-monthly-performance.timer
systemctl list-timers sharipovai-monthly-performance.timer --no-pager
```

Run a report manually:

```bash
/opt/sharipovai/.venv/bin/python scripts/phase10_monthly_report.py \
  --month 2026-07 \
  --output /var/lib/sharipovai/performance/2026-07.json
```

## Non-goals

Phase 10 does not prove profitability, authorize automatic scaling, enable leverage, enable Mainnet, or replace authenticated private order and execution evidence.
