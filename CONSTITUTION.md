# SharipovAI Constitution

Version: `2026.07-phase12-learning-validation-v17`  
Status: **Binding development and runtime policy**

## Safety and staged promotion

Capital preservation has priority. Mainnet execution is compiled out while
`MAINNET_EXECUTION_COMPILED=False`. The promotion stages remain:

```text
READ_ONLY -> PAPER -> TESTNET -> CONTROLLED_MAINNET -> SCALE
```

Skipping a stage is forbidden. Promotion is blocked by failed CI, missing walk-forward
out-of-sample evidence, missing buy-and-hold benchmarks, funding or cost gaps, stale
private streams, fill divergence, unresolved identities, reconciliation failure or a
breached risk limit. Failed automated gates cannot be overridden.

The canonical path is verified evidence, hard risk, Paper execution, bounded campaign,
private order and execution evidence, reconciliation, final report and manual decision.
No dashboard, agent, Learning Engine, scheduler, operator CLI or model output may create
an independent execution path.

## Research and evidence

Research uses versioned historical manifests, realistic fees, spread, slippage, impact,
funding and drawdown. Lookahead, leakage, random time-series splits and fabricated fills
are forbidden. Every candidate requires sequential walk-forward evidence and benchmarks.

The persistent Experiment Registry stores immutable identity, commit SHA, manifest hash,
strategy and backtest configuration, benchmark results, out-of-sample windows, Paper and
Testnet validation, automated report and explicit manual approval or rejection.

## Bounded Testnet contract

Initial Testnet notional remains **10–25 USDT** per accepted order. Completion requires
**20+ actual matched** fills, **zero orphan** evidence, zero unmatched or duplicate
identities, zero unresolved intents, actual private fees, fresh authenticated streams and
restart-safe reconciliation. Screenshots, copied JSON and synthetic fills are not proof.

## CI cleanroom and dashboard

Every pytest process uses the CI cleanroom before imports. Complete green required
workflows, dependency audit, compilation, foundation audits, crash tests and full pytest
are mandatory. Failed, cancelled, queued, missing or skipped checks are not green.

Sensitive APIs require administrator authorization before body parsing. Dashboard state
must be truthful, responsive and safe. It cannot change execution authority.

## Phase 12 evidence-driven self-learning

1. Outcome attribution accepts only verified Paper or authenticated Testnet evidence.
2. Outcomes are immutable, idempotent and SHA-256 protected; conflicting reuse blocks.
3. PnL and drawdown attribution must reconcile exactly. Non-finite evidence fails closed.
4. Persistent agent metrics include sample count, direction accuracy, calibration,
   attributed results and market-regime coverage.
5. Challenger creation uses the canonical Experiment Registry and immutable learning evidence.
6. Automatic research leadership is limited to **Paper research champion**.
   Automatic execution promotion is forbidden.
7. Testnet, scaling, deployment, capital, credentials and future Mainnet decisions remain
   separate evidence-gated manual decisions.
8. Challengers require sample, multi-regime, calibration, profitability, drawdown,
   walk-forward, benchmark and data-validation gates.
9. The self-learning supervisor is bounded and restart-safe and has no execution authority.

## Phase 12 Paper/Testnet validation

Expected-versus-actual Paper validation measures missing and unexpected fills, latency,
price, fee and fill-ratio errors. Paper-versus-Testnet shadow comparison measures latency,
slippage, partial fills, fees and fill divergence. Missing evidence, identity mismatch,
non-finite values or threshold breaches block eligibility. Validation is persisted with an
evidence SHA and attached to the Experiment Registry. A positive result is evidence only;
the final report, operator CLI and separate manual decision remain mandatory.

## Phase 12 release policy

Pre-merge requires the deterministic checklist and all required workflows green. Preflight
requires an exact SHA and clean canonical worktree. Post-deploy verification binds host,
runtime and image provenance to the reviewed SHA. Rollback is limited to a reviewed
ancestor and must preserve backup, health and provenance evidence. Failure remains blocked.

## Change history

- `2026.07-phase12-learning-validation-v17` — immutable outcome attribution, persistent
  challengers, Paper/Testnet validation and exact-SHA deployment evidence.
- `2026.07-phase11-production-launch-v16` — production audit, rollback and launch readiness.
