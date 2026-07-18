# Phase 9: Results, Scaling Preparation and Monitoring

Phase 9 converts a completed Phase 8 analysis into a detailed immutable campaign report and a separate fail-closed scaling plan.

## Results report

The report includes realized net/gross PnL, fees, Paper/Testnet divergence, closed trades, win rate, profit factor, maximum drawdown and closed notional. Only campaign-bound authenticated private fills are accepted.

## Scaling gates

Scaling is never automatic. The default preparation gates require:

- two successful campaigns;
- at least 40 total matched fills;
- all Phase 8 source gates clean;
- profit factor at least 1.05;
- win rate at least 40%;
- maximum drawdown no more than 250 bps;
- price divergence no more than 25 bps;
- fee ratio no more than 30 bps.

A passing plan proposes only the next bounded step from 25 to 37.5 USDT, capped at 50 USDT. It does not modify runtime flags, campaign policy or credentials.

## API

```text
POST /api/campaigns/phase9/report/{campaign_id}
GET  /api/campaigns/phase9/report/{campaign_id}
GET  /api/campaigns/phase9/reports
POST /api/campaigns/phase9/scaling-plan
GET  /api/campaigns/phase9/scaling-plans
```

## Deployment verification

```bash
sudo bash deploy/vps/phase9_post_deploy_verify.sh
```

The verifier checks rendered Compose, Python compilation, HTTP health and SQLite `PRAGMA quick_check`, then writes an atomic JSON report.
