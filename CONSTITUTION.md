# SharipovAI Constitution

Version: `2026.07-phase11-full-production-audit-v14`  
Status: **Binding development, deployment and runtime policy**

## 1. Capital protection

Capital preservation overrides speed, activity and profit. Live execution remains compiled out. No environment variable, dashboard, Telegram command, LLM, report, scaling activation or manual decision may override that lock.

## 2. Canonical execution authority

The only exchange-write entry remains `BybitExecutionClient.execute(ApprovedExecutionRequest)`. Every intent requires deterministic identity, durable reservation and authenticated private order/execution reconciliation. Ambiguous outcomes are never blind-retried.

## 3. Bounded Testnet authority

Testnet execution requires an explicit finite window, isolated credentials, fresh private streams, valid risk authority and an engaged kill switch until the approved opening step. Notional may never exceed the active authority or 50 USDT. Authority must be scoped, expiring, persisted, revocable and unable to enable live execution.

## 4. Evidence truth

Only campaign-bound authenticated private Testnet fills, actual fees, clean reconciliation and persisted reports are execution evidence. REST acceptance, screenshots, Paper fills, fixtures, dashboard state and activation records are not proof of execution or profitability.

## 5. Risk and capital

Position sizing is deterministic and uses the smallest applicable limit across equity risk budget, stop distance, volatility, per-position exposure, correlated-cluster exposure, active authority and the 50 USDT ceiling. Invalid or missing inputs fail closed.

## 6. Performance and drawdown

Performance snapshots and monthly reports are append-only evidence. Negative results and drawdown may not be deleted or hidden. Monthly drawdown above policy is critical; negative monthly PnL and missing matched fills are warnings.

## 7. Phase 11 production audit

Every release requires a deterministic audit covering:

1. live-execution locks;
2. kill-switch state;
3. secret-file hygiene;
4. required production assets;
5. deployment preflight and post-deploy verification;
6. responsive dashboard contracts;
7. bounded Testnet limits.

The audit emits critical blockers, warnings and a SHA-256 evidence hash. Any critical blocker means `blocked`. Missing, skipped, queued or stale evidence is not approval.

## 8. Dashboard

Campaign Operations, Scaling, Performance Overview and Production Overview are read-only visibility surfaces. They must remain responsive, usable on mobile, keyboard-compatible, reduced-motion aware and truthful under API failure. Theme preference may be stored locally. Dashboard code may not place orders or open campaign windows.

## 9. Monitoring, alerting and logging

Critical alerts include kill-switch anomalies, expired authority, drawdown breach, stale private evidence, reconciliation failure and unresolved identity. Logs must be structured, bounded and secret-free. Authorization headers, cookies, credentials and request bodies remain redacted or disabled.

## 10. Deployment

Deployment requires immutable target verification, backup, rendered configuration validation, compilation, focused tests, HTTP health, database integrity, bounded logs and rollback. Post-deploy evidence must be written atomically. A failed verifier requires rollback or an explicitly documented blocked state.

## 11. Real campaign readiness

A first real bounded Testnet campaign may start only after green CI, approved deployed SHA, isolated credentials without withdrawal/transfer permission, fresh authenticated private streams, verified reconciliation, working alerts and rollback, successful Phase 11 preflight and exact operator confirmation. Completion may be claimed only from actual authenticated private evidence.

## 12. CI and merge

Merge requires dependency checks, compileall, hard execution-lock tests, campaign/reconciliation tests, Phase 8-10 tests, Phase 11 audit/dashboard/deployment contracts and complete pytest. Failed, queued, skipped or missing checks are not approval.

## 13. Secrets and claims

Secrets are forbidden in Git, logs, metrics, reports and tests. SharipovAI must not promise profit or fabricate campaign completion, fills, fees, PnL, alerts, scaling, deployment success or production readiness.
