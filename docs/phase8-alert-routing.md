# Phase 8 Alert Routing

Critical campaign alerts remain persisted in `ProjectDatabase` before external delivery.

Supported external routes:

```env
ALERT_DELIVERY_ENABLED=1
ALERT_TELEGRAM_CHAT_ID=<chat-id>
ALERT_WEBHOOK_URL=https://<trusted-endpoint>
BOT_TOKEN=<telegram-bot-token>
```

Rules:

- Webhook delivery must use HTTPS.
- Telegram and webhook payloads are sanitized.
- Secrets are never included in an alert body.
- Delivery failure does not resolve or delete the alert.
- Repeat delivery respects the configured cooldown.
- Alerting is read-only and cannot change execution flags, campaign state or Mainnet availability.

Critical events include kill switch engagement during an active campaign, stale private streams, stale monitor heartbeat, reconciliation failure, blocked campaign, identity-integrity failures and orchestrator errors.
