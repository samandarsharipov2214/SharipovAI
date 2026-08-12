# Alpha Candidate v1 — Regime-Filtered Breakout

## Status

`RESEARCH ONLY` — this document defines the first explicitly non-benchmark SharipovAI hypothesis. It is not evidence of profitability and does not authorize Paper, Testnet, or Mainnet execution.

## Candidate identity

- Strategy: `regime_filtered_breakout_v1`
- Implementation: `trading_core/alpha_strategies.py`
- Market: liquid crypto Spot only for the first experiment
- Intended dataset: canonical Bybit Spot bars produced by `tools/import_bybit_spot_history.py`
- Preferred first universe: `BTCUSDT, ETHUSDT, SOLUSDT`
- Preferred first interval: `15m`

The existing `BuyAndHoldStrategy`, `TrendFollowingStrategy`, `BreakoutStrategy`, and `MeanReversionStrategy` remain benchmarks. They are not Alpha candidates.

## Economic hypothesis

A price breakout on a liquid crypto Spot market is more likely to persist when it is preceded by positive trend persistence, occurs in a moderate rather than dormant/extreme realized-volatility regime, and is confirmed by above-normal volume. Cooldown and bounded holding time are intended to reduce repeated entries in choppy regimes and uncontrolled exposure duration.

The candidate therefore requires all of the following before entry:

1. current completed observation breaks above the prior price channel by the preregistered buffer;
2. prior realized volatility is between the preregistered lower and upper regime bounds;
3. trend persistence exceeds the preregistered threshold;
4. current volume exceeds the prior-volume baseline by the preregistered multiplier.

It uses no future-derived feature. On close-derived historical bars, the canonical backtester executes the resulting signal on the next event of the same symbol.

## Default frozen parameters

The source of truth is `RegimeFilteredBreakoutConfig`. The first preregistration CLI serializes the exact values into the immutable experiment artifact. No value may be changed after the final holdout has been designated without creating a new experiment ID.

## Data eligibility

Final OOS may not run unless `HistoricalDataLoader.require_final_oos_eligible()` passes. The manifest must therefore carry explicit timestamp semantics, complete content hashes, attributable build commit, timezone-aware creation time, valid executable price provenance, and no observed missing intervals.

The preregistration stores the SHA-256 of the exact manifest file. The OOS runner recomputes that hash and fails closed on any mismatch.

## Research sequence

1. Build/validate the canonical historical dataset with public read-only data only.
2. Choose chronological Train, sequential Validation windows, and one untouched Final OOS range.
3. Run `tools/preregister_alpha_experiment.py`. This freezes code SHA, manifest SHA, hypothesis, falsification rule, parameters, cost model, risk model, execution timing, ranges, benchmarks, and acceptance criteria. It does **not** read/run Final OOS.
4. Do not modify the candidate, costs, risk model, acceptance gates, or dataset after preregistration. Any change requires a new experiment ID and a new genuinely untouched holdout.
5. Run `tools/run_preregistered_alpha_experiment.py` exactly once for that immutable experiment/result path.
6. Preserve the generated report and SHA-256 as evidence.

## Falsification and verdict

The exact falsification text is generated from `AlphaAcceptanceCriteria` and stored inside the preregistration artifact. The current result vocabulary is deliberately small:

- `ACCEPT_FOR_LONGER_PAPER`
- `REJECT_HYPOTHESIS`
- `INSUFFICIENT_SAMPLE`

Synthetic end-of-backtest liquidation is not counted as an organic closed trade for the sample-size or expectancy gates.

`ACCEPT_FOR_LONGER_PAPER` is only eligibility for a separately reviewed longer Paper campaign. It does not automatically start Paper and never enables Testnet or Mainnet.

## Benchmark comparison

Final OOS uses the same events, capital, costs, risk and timing assumptions for:

- Buy & Hold
- Trend Following
- Breakout benchmark
- Mean Reversion benchmark
- `regime_filtered_breakout_v1`

The report includes candidate rank and a preregistered risk-adjusted Buy & Hold gate. Consensus, AI confidence, or narrative quality cannot override a failed quantitative gate.

## Current evidence

Until a real final-OOS-eligible dataset is built, preregistered, and executed through this protocol, the only valid profitability statement is:

`INSUFFICIENT EVIDENCE`
