# SharipovAI OS

SharipovAI is a safety-first AI trading operating system for verified market evidence, deterministic risk, realistic Paper execution and bounded Bybit Testnet campaigns.

> **Production state:** Mainnet execution is compiled out. Production boots with the kill switch engaged. Testnet writes exist only inside an explicitly authorized bounded window.

## Phase 8

Phase 8 adds campaign launch operations and post-campaign analysis on top of Phase 7 deployment, monitoring and evidence controls.

Delivered:

- finite bounded Testnet campaign runner requiring exact operator confirmations;
- authenticated private fill monitoring;
- FIFO realized gross/net PnL analysis;
- actual fee, turnover and open-inventory analysis;
- Paper/Testnet price and fee divergence;
- hard evidence gates and deterministic recommendation;
- persistent Telegram/HTTPS webhook critical alerts;
- responsive live campaign and analysis dashboard;
- immutable database records and append-only analysis events;
- mandatory manual decision;
- Mainnet remains unavailable.

## Documentation

- [`CONSTITUTION.md`](CONSTITUTION.md)
- [`docs/phase7-production-testnet-campaign.md`](docs/phase7-production-testnet-campaign.md)
- [`docs/phase8-campaign-launch-and-analysis.md`](docs/phase8-campaign-launch-and-analysis.md)

## Campaign launch

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

Close the execution window after completion, failure, timeout or abort:

```bash
sudo bash deploy/vps/testnet_campaign_stop.sh I_APPROVE_RESTORE_PRODUCTION_KILL_SWITCH
```

## Post-campaign API

```text
POST /api/campaigns/phase8/analyze/{campaign_id}
GET  /api/campaigns/phase8/analysis/{campaign_id}
GET  /api/campaigns/phase8/analyses
```

Analysis never places orders, changes flags, approves promotion or enables Mainnet.

## Alert delivery

```env
CRITICAL_ALERT_MONITOR_ENABLED=1
ALERT_DELIVERY_ENABLED=1
ALERT_TELEGRAM_CHAT_ID=<chat-id>
ALERT_WEBHOOK_URL=https://<trusted-endpoint>
```

Telegram additionally uses `BOT_TOKEN`. Non-HTTPS webhooks are rejected. Delivery failure does not erase canonical alert evidence.

## Verification

```bash
python -m pip install -r requirements-dev.txt
python -m pip check
python -m compileall -q .
python -m pytest tests/test_phase8_post_campaign_analysis.py -q --tb=short
python -m pytest -q --tb=short
```

## Truth rule

A campaign is not real or completed until authenticated private Testnet fills, actual fees, clean reconciliation, 20+ matched fills and the canonical final report exist. Screenshots, synthetic fixtures and accepted REST responses are not proof.
