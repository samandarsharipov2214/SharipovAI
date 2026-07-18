# SharipovAI Constitution

Version: `2026.07-phase8-campaign-analysis-v11`  
Status: **Binding development, deployment and runtime policy**

## 1. Capital protection

Capital preservation overrides speed, activity and profit. Mainnet execution remains compiled out while `MAINNET_EXECUTION_COMPILED=False`. No environment variable, dashboard, Telegram command, LLM, experiment, report or manual decision may override that lock.

## 2. Canonical execution authority

The only exchange-write entry is `BybitExecutionClient.execute(ApprovedExecutionRequest)`. Dashboard, Telegram, schedulers, strategies, CLIs, agents and analysis services may not call an exchange endpoint directly.

Every intent requires deterministic identity, durable reservation and authenticated private order/execution reconciliation. Ambiguous outcomes are never blind-retried.

## 3. Bounded Testnet campaign

- Spot Testnet only.
- 10–25 USDT accepted notional per campaign order.
- One global non-terminal campaign.
- Isolated Testnet credentials without withdrawal/transfer permission.
- Fresh authenticated private `order` and `execution` streams.
- Restart-safe reconciliation.
- Mainnet compiled out.

Completion requires at least 20 matched Paper/Testnet fills, actual private fees and zero unmatched, orphan, duplicate, conflicting or unresolved evidence.

## 4. Production deployment

Production-safe configuration permanently keeps the kill switch on and Testnet writes off. An explicit ignored Testnet overlay may release only audited Testnet flags for a finite operator-approved window. Deployment requires preflight, verified backup, rendered Compose validation, health/database smoke checks and rollback.

## 5. Phase 8 launch truth

A start record, REST acceptance, screenshot, Paper fill or synthetic fixture is not real campaign evidence. A real launch may be claimed only when the VPS records authenticated private Bybit Testnet fills bound to the campaign.

Agents without VPS access and isolated Testnet credentials must state that launch cannot be confirmed.

## 6. Post-campaign analysis

Post-campaign analysis is evidence authority only. It may compute realized PnL, fees, turnover, inventory, Paper/Testnet divergence and a recommendation. It may not place orders, change flags, allocate capital, approve promotion or enable Mainnet.

Required properties:

1. canonical campaign-bound private fills only;
2. actual fees included;
3. open inventory exposed;
4. failed gates preserved;
5. immutable database evidence and append-only events;
6. separate manual decision required;
7. incomplete or negative evidence never converted to green.

## 7. Recommendation policy

`reject_or_rerun` is mandatory when a hard gate fails. `hold_for_more_testnet_evidence` is used when hard gates pass but evidence is weak. `eligible_for_manual_promotion_review` means review only; it is not promotion and cannot change runtime state.

## 8. Advanced alerting

Critical alerts for kill switch, multiple campaigns, stale private stream, stale heartbeat, reconciliation failure, blocked campaign, orphan/duplicate/unresolved/notional failure and orchestrator errors must be persisted and deduplicated.

Telegram and webhook delivery must be sanitized. Webhooks must use HTTPS. Delivery failure cannot erase or resolve canonical alert evidence.

## 9. Live dashboard

Live monitoring is read-only. It may show fills, fees, PnL, divergence, gates, recommendation and alerts. It cannot install credentials, release the kill switch, submit orders, approve promotion or enable Mainnet.

## 10. CI and merge

Merge requires dependency audit, compileall, hard Mainnet lock tests, campaign/reconciliation tests, Phase 8 analytics tests, dashboard contracts and complete pytest. Failed, queued, skipped or missing checks are not approval.

## 11. Secrets and claims

Secrets are forbidden in Git, logs, metrics, reports and tests. SharipovAI must not promise profit or fabricate campaign completion, PnL or private fills.
