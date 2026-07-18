# SharipovAI Constitution

Version: `2026.07-phase9-results-scaling-v12`  
Status: **Binding development, deployment and runtime policy**

## 1. Capital protection

Capital preservation overrides speed, activity and profit. Mainnet execution remains compiled out while `MAINNET_EXECUTION_COMPILED=False`. No environment variable, dashboard, Telegram command, LLM, experiment, report, scaling plan or manual decision may override that lock.

## 2. Canonical execution authority

The only exchange-write entry is `BybitExecutionClient.execute(ApprovedExecutionRequest)`. Dashboard, Telegram, schedulers, strategies, CLIs, agents and analysis services may not call an exchange endpoint directly. Every intent requires deterministic identity, durable reservation and authenticated private order/execution reconciliation. Ambiguous outcomes are never blind-retried.

## 3. Bounded Testnet campaign

- Spot Testnet only.
- 10–25 USDT accepted notional per campaign order until a separately audited scaling release is approved.
- One global non-terminal campaign.
- Isolated Testnet credentials without withdrawal or transfer permission.
- Fresh authenticated private `order` and `execution` streams.
- Restart-safe reconciliation.
- Mainnet compiled out.

Completion requires at least 20 matched Paper/Testnet fills, actual private fees and zero unmatched, orphan, duplicate, conflicting or unresolved evidence.

Canonical CI audit concepts: `matched_fills`, `zero_identity_failures`, `private_evidence`, `final_report`, `ci_cleanroom`, `operator_cli`, `mainnet_lock`.

## 4. Campaign result authority

Phase 9 reports may use only campaign-bound authenticated private fills and the persisted Phase 8 analysis. Reports must expose realized gross/net PnL, actual fees, closed trades, open evidence gaps, Paper/Testnet divergence, win rate, profit factor, maximum drawdown and closed notional. Missing or non-finite evidence fails closed.

Reports are evidence authority only. They cannot place orders, change credentials, modify risk limits, change notional, approve promotion or enable Mainnet.

## 5. Scaling preparation

Scaling is never automatic. A scaling plan is a persisted proposal for manual review only.

Default gates require:

1. at least two completed successful bounded campaigns;
2. at least 40 total matched fills;
3. all source gates clean;
4. profit factor at least 1.05;
5. win rate at least 40 percent;
6. maximum drawdown at most 250 bps;
7. absolute price divergence at most 25 bps;
8. fee ratio at most 30 bps.

A passing plan may propose only one step from 25 to 37.5 USDT and may never exceed 50 USDT. It does not change runtime state. A separate audited policy change, CI, owner approval and finite Testnet release are required before any larger notional becomes executable.

## 6. Advanced monitoring and alerts

Dashboard monitoring is read-only. Critical drawdown, source-gate failure, stale private evidence, reconciliation failure, orphan/duplicate/unresolved identity and campaign blockers must remain visible.

Telegram and webhook delivery must be sanitized and deduplicated. Webhooks must use HTTPS. Delivery failure cannot erase, resolve or downgrade canonical alert evidence. Telegram notification is never execution authority.

## 7. Production deployment and logging

Production-safe configuration permanently keeps the kill switch on and Testnet writes off. Deployment requires immutable-target preflight, verified backup, rendered Compose validation, Python compilation, HTTP health, SQLite `PRAGMA quick_check`, bounded logs and rollback.

Logs must be structured, bounded and secret-free. Sensitive request metadata must be redacted. Request and response bodies are disabled by default. A post-deploy verification report must be written atomically.

## 8. Manual decisions

`eligible_for_manual_scaling_review` means review only. It is not a capital allocation, deployment, promotion or execution approval. Actor and reason are mandatory. Failed gates cannot be overridden by UI, Telegram, LLM output or narrative confidence.

## 9. CI and merge

Merge requires dependency audit, compileall, hard Mainnet lock tests, campaign/reconciliation tests, Phase 8 analysis tests, Phase 9 report/scaling tests, dashboard contracts, deployment contracts and complete pytest. Failed, queued, skipped or missing checks are not approval.

## 10. Secrets and claims

Secrets are forbidden in Git, logs, metrics, reports and tests. SharipovAI must not promise profit or fabricate campaign completion, fills, PnL, risk metrics, alert delivery or scaling eligibility.
