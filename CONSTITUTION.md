# SharipovAI Constitution

Version: `2026.07-automatic-shadow-campaign-v6`  
Status: **Binding development and runtime policy**

This document defines non-negotiable rules. Code, configuration, dashboards,
AI outputs, CI and deployment automation must obey it. A conflicting feature is
invalid even when it appears profitable.

## 1. Capital protection

1. Capital preservation has priority over activity, speed and profit.
2. Mainnet execution is compiled out at the current development stage.
3. Environment variables, Telegram, dashboard, LLM output, experiment results and
   stored state cannot override the compile lock.
4. Automated API keys must not have withdrawal or transfer permissions.
5. Future live operation requires a separate limited subaccount, expiring manual
   approval and a new audited release. It is not enabled by this branch.
6. Automatic martingale, leverage increase, averaging down and all-in allocation
   are forbidden.
7. Promotion records are research authority only. They are never execution authority.

## 2. Promotion stages

```text
READ_ONLY -> PAPER -> TESTNET -> CONTROLLED_MAINNET -> SCALE
```

Skipping a stage is forbidden.

- `READ_ONLY`: public/private reads without exchange writes.
- `PAPER`: virtual capital and fills using verified market evidence.
- `TESTNET`: writes only through an `ApprovedExecutionRequest`, durable idempotency,
  bounded shadow mode, actual Bybit filters and verified private order evidence.
- `CONTROLLED_MAINNET`: unavailable while `MAINNET_EXECUTION_COMPILED=False`.
- `SCALE`: never automatic; requires measured live evidence and owner approval.

Promotion is blocked by failed/skipped CI, unresolved orders, stale private stream,
reconciliation errors, insufficient out-of-sample evidence, fill divergence,
data-quality failure or a breached drawdown/loss limit.

## 3. Canonical decision and execution path

```text
Market Intelligence
  -> Portfolio snapshot
  -> Risk Engine hard limits
  -> Risk-based capital allocation
  -> Decision Quality
  -> Security Guard
  -> TradingCandidate validation
  -> Paper execution
  -> Testnet shadow plan
  -> Actual Bybit fee/instrument validation
  -> ApprovedExecutionRequest
  -> Idempotency reservation
  -> Testnet executor
  -> Private order WebSocket evidence
  -> Runtime Fill Harvester
  -> Reconciliation and divergence evidence
```

No dashboard, Telegram handler, Learning Engine, agent, strategy or LLM may call
an exchange order endpoint directly. The only exchange write entry is:

```python
BybitExecutionClient.execute(approved_request)
```

## 4. Idempotency and unknown outcomes

1. Every execution request has a deterministic `sai_...` `orderLinkId` derived
   from immutable intent.
2. The intent is reserved in `ProjectDatabase` before the network request.
3. The same intent cannot be submitted twice.
4. Timeout or transport failure after reservation is an ambiguous financial
   outcome, not a retry signal.
5. Ambiguous requests remain unresolved until private order evidence or explicit
   operator reconciliation resolves them.
6. Startup remains blocked for missing journal evidence, orphan private orders,
   identifier mismatch, unresolved intents or an unhealthy private stream.
7. Retry requires a new explicit attempt identity.

## 5. Private order WebSocket gate

Testnet execution requires a read-only authenticated private WebSocket subscribed
to the Bybit `order` topic.

Mandatory evidence:

- feature enabled;
- worker running;
- isolated Testnet credentials configured;
- connected and authenticated;
- `order` topic subscribed;
- fresh persisted heartbeat;
- correct Testnet environment;
- no unresolved reconciliation error.

The stream has no create/amend/cancel capability. A missing or stale heartbeat
blocks Testnet startup. REST acceptance alone is not final execution evidence.

## 6. Hard risk and capital limits

Hard limits always override confidence, consensus, strategy output and expected
profit. Mandatory blocks include stale data, kill switch, invalid instrument,
drawdown/loss limits, total/symbol/correlation exposure, liquidity floor,
maximum positions, missing Evidence, non-finite values, expired requests,
duplicate/unresolved identities and Mainnet environment.

Default research/paper policy:

| Rule | Default |
| --- | ---: |
| Cash reserve | 20% |
| Maximum total exposure | 80% |
| Maximum one position | 20% |
| Maximum one symbol | 20% |
| Maximum correlated group | 35% |
| Maximum risk per trade | 1% |
| Maximum daily loss | 2% |
| Leverage | 1× |

Soft risk may only reduce size: `LOW=1.0`, `MEDIUM=0.6`, `HIGH=0.25`,
`CRITICAL=0.0`.

## 7. Paper-trading realism

Only capital and fills are virtual. Quotes, timestamps, maker/taker fees,
bid/ask spread, market impact, slippage, funding, risk, drawdown and Evidence are
production-style inputs.

Paper state must be durable, atomic, revisioned and recoverable. Synthetic prices,
fabricated trades and fake catch-up fills are forbidden.

A paper trade may reach Testnet only when it references a stored canonical
`TradingCandidate`, is recent, matches symbol/side/price and passes fresh validation.

## 8. Backtesting and historical-data integrity

1. Backtests process immutable events in `(timestamp, symbol)` order.
2. Lookahead, future leakage, duplicate bars and random time-series splits are forbidden.
3. Results include spread, maker/taker fees, slippage, participation impact and funding.
4. Backtest, paper and Testnet converge on shared models, costs, risk and capital logic.
5. Every run records strategy/config version, manifest identity and commit SHA.
6. Historical datasets require a versioned manifest and validation.
7. Missing intervals are visible evidence and are never silently fabricated.
8. A backtest is research evidence, never execution permission.
9. Every candidate is compared with buy-and-hold, trend, breakout and mean-reversion.
10. Sequential walk-forward out-of-sample evidence is mandatory for promotion gate review.

## 9. Persistent Experiment Registry

Every promotion candidate must exist in the canonical `ExperimentRegistry` with:

- immutable experiment ID;
- source commit SHA;
- validated manifest ID, version and SHA-256 identity;
- strategy configuration;
- backtest/cost configuration;
- walk-forward results;
- mandatory benchmark table;
- data-validation result;
- paper summary where applicable;
- Paper/Testnet fill-validation report where applicable;
- automated promotion report;
- explicit manual decision with actor, reason and timestamp.

Experiment lifecycle:

```text
created -> running -> completed -> promotion_pending -> promoted/rejected
```

A promoted experiment is immutable. A rejected experiment may be re-evaluated only
with new Evidence. The registry uses optimistic versions and append-only events.
It does not modify environment variables, deploy code or change execution mode.

## 10. Automatic experiment execution

The Automatic Experiment Runner must:

1. validate the versioned Parquet manifest before loading any market event;
2. derive one deterministic fingerprint from commit SHA, manifest, strategy config,
   backtest config and walk-forward config;
3. refuse a duplicate experiment with the same immutable fingerprint;
4. run sequential walk-forward evaluation and all mandatory benchmarks;
5. persist data validation, walk-forward, benchmarks and run summary in a write-once
   immutable result namespace;
6. store each immutable result SHA-256 in the Experiment Registry;
7. mark the experiment failed when execution is incomplete;
8. never change a strategy stage, execution flag, champion or deployment automatically.

An automatic experiment is reproducibility infrastructure, not permission to trade.

## 11. Actual Bybit reference-data rules

Execution-related quantity and cost assumptions must use actual Bybit read-only
reference data when Testnet shadow mode is enabled:

- account-specific maker/taker fee tier from `/v5/account/fee-rate`;
- `tickSize`, `qtyStep`, minimum quantity, minimum notional and maximum market
  quantity from `/v5/market/instruments-info`;
- explicit environment, symbol, category, source and expiration timestamp;
- bounded canonical `ProjectDatabase` cache;
- fail-closed behavior when credentials, data, schema or freshness are invalid.

Quantity is always rounded **down** to `qtyStep`. Rounding up, guessing a missing
minimum, or using old screenshots/static tables as execution authority is forbidden.
Static fee tables may remain educational fallbacks only; they cannot authorize a
Testnet order.

## 12. Testnet shadow mode

Shadow mode gives Paper and Testnet one source candidate and separate execution
observations.

Mandatory rules:

- Paper sizing and Paper accounting are not changed by shadow execution;
- Testnet receives a fresh candidate derived from the same canonical evidence;
- the source candidate ID, Testnet candidate ID and `shadow_pair_id` are persisted;
- Testnet notional is capped at the lower of execution policy and **25 USDT**;
- environment variables cannot raise the shadow cap above 25 USDT in this build;
- quantity is normalized with actual Bybit instrument rules;
- an order below minimum quantity/notional or above market limits is blocked;
- dynamic fee/instrument evidence is written into bridge and journal records;
- private WebSocket and startup reconciliation remain mandatory;
- Mainnet remains compiled out.

Shadow mode is disabled by default and does not replay historical Paper trades.

## 13. Runtime Fill Harvester

The Runtime Fill Harvester automatically joins:

- canonical Paper trade identity;
- shadow bridge record;
- `orderLinkId`;
- private Testnet order lifecycle and partial fills.

It calculates and persists latency, slippage, fee, fill-ratio, partial-fill and
unmatched-fill divergence through `FillDivergenceAnalyzer` and
`FillValidationRepository`.

Rules:

1. report identity is derived from experiment and immutable execution evidence;
2. an unchanged evidence set cannot create a conflicting report;
3. unmatched Paper or Testnet observations are blocking evidence;
4. partial fills are aggregated from private order state, not inferred from REST;
5. the harvester is read-only with respect to exchange execution;
6. the background worker is disabled by default and requires `SHADOW_EXPERIMENT_ID`;
7. a divergence report does not promote a strategy automatically.

## 14. Champion–Challenger registry

Each bounded strategy scope has exactly one champion and zero or more challengers.

- A challenger requires a completed Experiment Registry record.
- A champion requires an experiment already promoted for the exact target stage.
- Automated promotion gates and manual experiment approval must both be present.
- The leadership decision requires `PROMOTE:<scope>:<experiment>:<stage>`.
- Evidence SHA-256, actor, reason, previous champion and timestamp are persisted.
- A strategy cannot be both active champion and active challenger.
- Champion selection does not deploy code, enable Testnet, enable Mainnet or change capital.
- Replacing a champion preserves the retired champion and full history.
- Comparison uses the same immutable Experiment Registry results.

No optimizer, Learning Engine, dashboard or AI confidence score may appoint a champion
without the required Evidence.

## 15. Research -> PAPER gate

Promotion to PAPER requires:

- completed persistent experiment;
- valid commit SHA;
- validated versioned data manifest;
- fees, slippage, impact and funding included;
- lookahead disabled;
- at least 6 out-of-sample walk-forward windows;
- at least 60% profitable OOS windows after all costs;
- positive aggregate OOS net PnL;
- maximum drawdown within hard policy;
- positive risk-adjusted score;
- candidate beats buy-and-hold and at least two mandatory benchmarks;
- no single positive window contributes more than 40% of positive OOS PnL;
- no material data-quality warning;
- green dependency audit, critical coverage and complete pytest;
- manual owner review.

Automated evaluation returns only `eligible_for_manual_approval`. Promotion is
persisted only after the exact experiment/stage approval token and a reason are
provided. This does not enable Testnet.

## 16. PAPER -> TESTNET gate

PAPER to TESTNET additionally requires:

- sustained paper evidence across multiple regimes;
- zero hard-risk breaches;
- zero unresolved execution intents;
- at least 20 matched Paper/Testnet fill pairs;
- zero unmatched Paper and Testnet fills in the promotion sample;
- p95 latency divergence <= 2000 ms;
- p95 slippage divergence <= 15 bps;
- Testnet partial-fill rate <= 20%;
- maximum fill-ratio divergence <= 0.10;
- fee divergence within documented policy;
- fresh authenticated/subscribed private order WebSocket heartbeat;
- successful startup reconciliation;
- explicit General Controller and owner approval.

Manual approval creates a promotion record only. Testnet execution still requires
its separate default-off flags, isolated credentials, stage gate, kill switch and
fresh reconciliation at runtime.

## 17. TESTNET -> CONTROLLED_MAINNET gate

This transition is impossible while `MAINNET_EXECUTION_COMPILED=False`.

A future audited build must additionally require a separate limited subaccount,
withdrawal/transfer permissions disabled, a defined observation period, zero
orphan/duplicate/unresolved orders, verified restart recovery, actual cost
consistency, daily/weekly loss governors, 1× initial leverage, expiring owner unlock,
rollback procedure and jurisdiction-specific legal review.

No AI confidence, benchmark rank, manual database edit or dashboard action can
bypass the compile lock.

## 18. Manual approval rules

1. Every promotion target requires a new automated report.
2. Approval token is bound to experiment ID and target stage.
3. Champion approval is additionally bound to strategy scope.
4. Approval requires an authenticated actor and non-empty reason.
5. A failed automated gate cannot be overridden manually.
6. Approval does not alter runtime flags, credentials, capital or deployment.
7. Promotion to a later stage does not erase earlier Evidence.
8. Rejection is persisted with actor, reason and timestamp.

## 19. Canonical architecture

SharipovAI has nine top-level AI organs: General Controller, Market Intelligence,
News Intelligence, Risk Engine, Portfolio Engine, Virtual Execution, Decision
Quality, Learning Engine and Security Guard.

Infrastructure such as registries, storage, monitoring, transport, validation,
idempotency, automatic experiments and backtesting is not a new AI organ.

## 20. Learning and strategy changes

Learning may create lessons, proposals and challenger strategies. It may not edit
or deploy production rules, enable exchange writes, increase capital/leverage,
remove Risk/Security vetoes, retry unresolved orders, treat confidence as proof,
optimize against a seen OOS window, omit unfavorable benchmarks or replace the
champion without approved Evidence.

## 21. Database, Evidence and observability

`ProjectDatabase` is the canonical source of truth for experiment identity,
immutable result references, champion/challenger leadership, execution intents,
private order health, fill validation, audit, learning and project memory. JSON
files are bounded backups/caches.

Secrets, seed phrases, keys, credentials and tokens are forbidden in Git, logs,
metrics, experiments, validation reports, Evidence and test artifacts.

## 22. CI and merge rules

Merge requires dependency installation, `pip check`, `pip-audit`, compilation,
critical imports, hard Mainnet lock, execution/idempotency/reconciliation tests,
private-stream tests, risk/capital/backtest tests, manifest and benchmark tests,
automatic experiment tests, actual Bybit reference tests, shadow mode tests,
runtime fill harvester tests, champion/challenger tests, dashboard auth tests,
execution/research/promotion/campaign/release audits, critical coverage, complete
pytest, retained artifacts, no runtime-state commit and an explicit rollback path.

A static score, partial suite or AI statement cannot override failed or skipped CI.
Testnet and Mainnet remain disabled by default in CI.

## 23. Profit and user claims

SharipovAI reports measured results after all modeled costs. It must not promise
guaranteed income, fabricate performance or scale capital based only on a backtest,
confidence score or narrative.

## Change history

| Version | Date | Summary |
| --- | --- | --- |
| `2026.07-automatic-shadow-campaign-v6` | 2026-07-14 | Automatic immutable experiments, actual Bybit fee/instrument rules, bounded Testnet shadow mode, runtime fill harvesting and evidence-gated champion/challenger leadership. |
| `2026.07-experiment-promotion-v5` | 2026-07-14 | Persistent experiment identity, Paper/Testnet divergence metrics, private WebSocket startup evidence and manual staged promotion decisions. |
| `2026.07-research-promotion-v4` | 2026-07-14 | Versioned Parquet/DuckDB data, funding/impact modeling, walk-forward evaluation, benchmarks and operational metrics. |
| `2026.07-execution-research-v3` | 2026-07-14 | Durable idempotency, startup reconciliation, hard risk/correlation limits and shared event-driven backtesting. |
| `2026.07-safety-foundation-v2` | 2026-07-14 | Mainnet compile lock, canonical execution request, atomic paper state and truthful CI. |
