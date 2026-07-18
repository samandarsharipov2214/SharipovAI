# Phase 8 — Campaign Launch and Post-Campaign Analysis

Status: implementation is ready; a real campaign is not claimed until the VPS contains authenticated private Bybit Testnet fills.

## Launch

Phase 8 reuses the Phase 7 bounded runtime window and canonical campaign runner. It does not create a second order path.

```bash
sudo bash deploy/vps/testnet_campaign_deploy.sh I_APPROVE_BOUNDED_TESTNET_RUNTIME_DEPLOYMENT

docker exec sharipovai python scripts/first_testnet_campaign.py \
  --experiment-id '<promoted-experiment-id>' \
  --scope BTCUSDT \
  --actor '<operator>' \
  --output-dir /var/lib/sharipovai/evidence/testnet-campaigns \
  --start-confirmation I_APPROVE_BOUNDED_TESTNET_SHADOW_CAMPAIGN \
  --cycle-confirmation I_APPROVE_BOUNDED_TESTNET_CAMPAIGN_CYCLE \
  --report-confirmation I_APPROVE_IMMUTABLE_CAMPAIGN_REPORT
```

Always close the window:

```bash
sudo bash deploy/vps/testnet_campaign_stop.sh I_APPROVE_RESTORE_PRODUCTION_KILL_SWITCH
```

## Automatic analysis

`PostCampaignAnalysisService` computes:

- FIFO realized gross and net PnL;
- actual fees and fee ratio;
- actual versus Paper average-price divergence;
- actual versus expected fee divergence;
- open inventory;
- hard evidence gates;
- a recommendation: reject/rerun, hold for more evidence, or eligible for manual promotion review.

Analysis is read-only with respect to execution and always requires a separate manual decision.

## APIs

```text
POST /api/campaigns/phase8/analyze/{campaign_id}
GET  /api/campaigns/phase8/analysis/{campaign_id}
GET  /api/campaigns/phase8/analyses
```

## Alerting

Phase 7 persistent alerts remain authoritative and already support sanitized Telegram and HTTPS webhook delivery. Phase 8 analysis never hides operational alerts and never converts failed gates to green.

## Truth rule

Without VPS access, isolated Testnet credentials, a promoted experiment and authenticated private fills, no agent may claim that the first real campaign was launched or completed.
