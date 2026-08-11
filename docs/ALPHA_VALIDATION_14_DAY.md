# SharipovAI Alpha Validation — 14-day evidence gate

Status: active research policy for the `alpha-validation/edge-paper-20260812` branch.

## Objective

For the next 14 days the project optimizes for one question: **does at least one frozen trading hypothesis show reproducible positive out-of-sample net expectancy after realistic costs?**

A negative result is valid evidence. It is better than adding infrastructure around an unproven strategy.

## Engineering freeze

Unless a change is required to preserve research correctness, evidence integrity, data durability, or an existing safety invariant, defer:

- new AI organs/agents and Meta-AI layers;
- UI/theme/SaaS/billing feature work;
- Telegram presentation improvements;
- Mainnet/Testnet enablement or notional scaling;
- broad legacy cleanup that does not affect canonical Paper/research truth;
- new architectural abstractions without a demonstrated defect.

Safety fixes remain allowed. Mainnet remains compiled out and execution kill-switch contracts remain unchanged.

## Research integrity gate (must pass before interpreting PnL)

1. Determine the exact semantics of every `MarketEvent` used by research: quote/tick, candle close, or synthetic transformation.
2. Prove that the strategy sees only information available at the decision timestamp.
3. Explicitly document execution timing. Same-event execution is acceptable only for point-in-time executable quote/tick observations. Candle-close signals must not receive fills using information unavailable at order time.
4. Verify fees, spread, slippage, market impact and funding are included consistently.
5. Historical inputs must have provenance, immutable manifest/checksum, monotonic timestamps, duplicate/gap checks, and no fabricated missing data.
6. Train/calibration data and untouched OOS evaluation data must be separated before parameter selection.

No strategy may be promoted to Paper review while any item above is unknown.

## Strategy freeze

The existing deterministic baseline suite is the starting universe:

- Buy and Hold — benchmark only;
- Trend Following;
- Breakout;
- Mean Reversion.

Select at most **two** candidate strategies for the first campaign. Freeze the hypothesis and parameter-selection procedure before opening the final OOS segment. Do not add an AI ensemble to rescue a strategy that has no independent edge.

## Evaluation contract

Every candidate and benchmark must use the same:

- historical event stream;
- cost model;
- capital allocation/risk policy;
- walk-forward boundaries;
- execution-timing semantics;
- reporting pipeline.

Required report fields:

- gross PnL;
- fees;
- spread/slippage/market-impact cost;
- funding cost;
- net PnL;
- net expectancy per closed trade;
- profit factor;
- max drawdown;
- closed-trade count;
- Sharpe/Sortino as secondary statistics, not primary gates;
- profitable walk-forward windows / total windows;
- Buy-and-Hold comparison;
- comparison against the other deterministic baseline strategies;
- symbol/time/regime concentration;
- confidence interval or bootstrap uncertainty for expectancy when sample size permits.

## 14-day schedule

### Days 1–2 — trust the research

- close execution-timing ambiguity;
- verify data provenance and cost accounting;
- enforce canonical risk-policy relationships;
- fix only defects capable of invalidating trading evidence.

Exit: research integrity gate is fully known and tested.

### Days 3–4 — freeze hypotheses and dataset

- select up to two candidate strategies;
- freeze dataset manifest/SHA and untouched OOS segment;
- record strategy hypothesis and parameter-selection procedure before final OOS evaluation.

Exit: reproducible campaign specification exists.

### Days 5–7 — walk-forward/OOS

Run candidates and benchmarks under identical costs. Produce machine-readable and human-readable reports.

Exit: complete OOS evidence without post-hoc parameter changes.

### Days 8–9 — GO / REJECT / INSUFFICIENT EVIDENCE

A candidate is not accepted merely because aggregate PnL is positive. Require positive cost-adjusted expectancy plus acceptable drawdown and cross-window stability. Sample sufficiency must be justified from observed trade frequency/variance; `100–200` trades and `PF >= 1.2` are useful review heuristics, not universal laws.

If the final OOS result is non-positive after costs, reject the hypothesis. Do not tune against the same final OOS segment.

### Days 10–12 — canonical Paper only

Only accepted candidates enter Paper review. Paper must use the same signal, sizing and cost assumptions as research and must be restart-safe with immutable fills/settlements.

No Testnet in this phase.

### Days 13–14 — verdict

Compare research and Paper evidence. Final result for each hypothesis must be one of:

- `ACCEPT_FOR_LONGER_PAPER`;
- `REJECT_HYPOTHESIS`;
- `INSUFFICIENT_SAMPLE`.

Do not claim profitability probability from insufficient evidence.

## Primary KPIs

Engineering activity is not a success metric for this phase. Primary KPIs are:

1. cost-adjusted net expectancy;
2. profit factor;
3. max drawdown;
4. independent closed-trade sample size;
5. OOS performance versus Buy-and-Hold and deterministic baselines;
6. stability across walk-forward windows / market regimes;
7. research throughput: number of pre-registered hypotheses honestly accepted or rejected without reusing the final holdout.

## Risk-policy invariant

Capital allocation must never be looser than the downstream hard risk limits for equivalent concepts. In particular, default single-position/symbol, total portfolio, correlated-exposure and daily-loss caps must remain at or inside the corresponding `RiskLimits` hard boundaries. If two values intentionally represent different concepts, that distinction must be explicit and covered by tests.

## GO / NO-GO discipline

Continue an individual strategy hypothesis only if evidence survives costs and untouched OOS evaluation. Change the hypothesis rather than adding infrastructure when edge disappears after costs.

At the project level, if repeated pre-registered hypotheses fail to produce robust OOS evidence over the research window, conduct a strategy/data review before authorizing further nonessential engineering.

## Explicit non-goals

This phase does not authorize:

- Mainnet;
- enabling Testnet;
- automatic strategy promotion;
- increasing capital;
- weakening execution/risk/security gates;
- claiming future profitability from backtest results.
