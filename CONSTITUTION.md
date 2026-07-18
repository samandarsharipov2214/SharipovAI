# SharipovAI Constitution

Version: `2026.07-phase10-controlled-scaling-performance-v13`  
Status: **Binding development, deployment and runtime policy**

## 1. Capital protection

Capital preservation overrides speed, activity and profit. Mainnet execution remains compiled out while `MAINNET_EXECUTION_COMPILED=False`. No environment variable, dashboard, Telegram command, LLM, experiment, report, scaling plan, activation or manual decision may override that lock.

## 2. Canonical execution authority

The only exchange-write entry is `BybitExecutionClient.execute(ApprovedExecutionRequest)`. Dashboard, Telegram, schedulers, strategies, CLIs, agents, analysis services and scaling services may not call an exchange endpoint directly. Every intent requires deterministic identity, durable reservation and authenticated private order/execution reconciliation. Ambiguous outcomes are never blind-retried.

## 3. Controlled Testnet scaling

Phase 10 scaling may execute only after an eligible persisted Phase 9 plan and exact owner confirmation:

`I_APPROVE_CONTROLLED_TESTNET_NOTIONAL_SCALING`

A valid activation must be:

1. Testnet-only;
2. scope-bound;
3. expiring;
4. persisted with actor, campaign IDs, previous notional, authorized notional and authority hash;
5. revocable;
6. no greater than 1.5 times the previous notional;
7. no greater than 50 USDT;
8. unable to override the kill switch;
9. unable to enable Mainnet;
10. consumed only through the existing canonical execution path.

An activation is authority to validate a bounded request. It is not an order, campaign success claim, profit guarantee or permanent capital allocation. Expired, revoked, mismatched-scope or excessive-notional authority fails closed.

## 4. Campaign and scaling evidence

Only campaign-bound authenticated private Testnet fills, actual fees, clean identity reconciliation and persisted campaign reports are execution evidence. REST acceptance, Paper fills, screenshots, synthetic fixtures and activation records are not proof of execution or profitability.

Scaling eligibility requires at least two clean campaigns, at least 40 matched fills, source gates clean, profit factor at least 1.05, win rate at least 40 percent, maximum drawdown at most 250 bps, absolute price divergence at most 25 bps and fee ratio at most 30 bps.

## 5. Risk and capital engine

Position sizing must be deterministic and use the smallest applicable limit. Inputs include equity, stop distance, realized volatility, per-position exposure, correlated-cluster exposure and active scaling ceiling.

Default limits:

- risk budget: 0.25 percent of equity;
- maximum single-position exposure: 5 percent of equity;
- maximum correlated-cluster exposure: 10 percent of equity;
- correlation threshold: absolute correlation of 0.70;
- absolute Testnet ceiling: 50 USDT.

Invalid equity, invalid stop distance, non-finite inputs, exhausted cluster capacity, missing scaling authority or expired authority fail closed. Correlation data may reduce size but may never increase it beyond another limit.

## 6. Long-term performance authority

Performance snapshots and monthly reports must be persisted. Monthly reports expose at minimum net PnL, actual fees, matched fill count and maximum drawdown. Historical negative results cannot be deleted, converted to green or omitted from a later aggregate.

Maximum monthly drawdown above 250 bps is critical. Negative monthly net PnL and reports without matched fills are warnings. Alert delivery failure cannot erase canonical evidence.

## 7. Monitoring and notifications

Critical alerts include expired active scaling authority, drawdown breach, stale private evidence, reconciliation failure, orphan/duplicate/unresolved identity and kill-switch anomalies. Critical alerts are eligible for dashboard, Telegram and HTTPS webhook delivery through the existing persistent alert authority.

Telegram is notification only. It cannot activate scaling, revoke evidence, submit orders or override failed gates.

## 8. Dashboard

Scaling Dashboard and Performance Overview are read-only views. They may show active authority, scope, authorized notional, expiry, monthly PnL, fees, matched fills, drawdown and alerts. They may not display Mainnet as enabled, create a second execution route or hide missing evidence.

## 9. Deployment and logging

Production-safe configuration permanently keeps the kill switch on and Testnet writes off outside finite approved windows. Deployment requires immutable-target preflight, verified backup, rendered Compose validation, Python compilation, HTTP health, SQLite integrity, bounded structured logs and rollback.

Secrets, authorization headers, cookies and API keys must be redacted. Request and response bodies remain disabled by default.

## 10. CI and merge

Merge requires dependency audit, compileall, hard Mainnet lock tests, campaign/reconciliation tests, Phase 8 analysis tests, Phase 9 report/scaling tests, Phase 10 activation, capital-engine, monitoring and dashboard contracts, deployment contracts and complete pytest. Failed, queued, skipped or missing checks are not approval.

## 11. Secrets and claims

Secrets are forbidden in Git, logs, metrics, reports and tests. SharipovAI must not promise profit or fabricate campaign completion, fills, PnL, risk metrics, alert delivery, scaling eligibility or scaling execution.
