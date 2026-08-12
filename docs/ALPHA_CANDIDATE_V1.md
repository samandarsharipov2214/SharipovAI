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

The source of truth is `RegimeFilteredBreakoutConfig`. The first preregistration CLI serializes the exact values into the immutable experiment artifact. No value may be changed after the final holdout has been designated without creating a new experiment ID and a genuinely new untouched holdout.

## Data eligibility

Final OOS may not run unless `HistoricalDataLoader.require_final_oos_eligible()` passes. The manifest must carry explicit timestamp semantics, complete content hashes, attributable build commit, timezone-aware creation time, valid executable price provenance, no observed missing/irregular bar intervals, and complete start/end coverage for every declared symbol.

The preregistration stores the SHA-256 of the exact manifest file. The OOS runner recomputes that hash and validates the underlying Parquet hashes before any final result is accepted.

## Research sequence

1. Build/validate the canonical historical dataset with public read-only data only.
2. Choose chronological Train, sequential Validation windows, and one untouched Final OOS range.
3. Use a **clean Git worktree** and run `tools/preregister_alpha_experiment.py`. It freezes code SHA, manifest SHA, hypothesis, falsification rule, parameters, cost model, risk model, execution timing, ranges, benchmarks, and acceptance criteria. It does **not** run Final OOS.
4. Do not modify the candidate, costs, risk model, acceptance gates, dataset, or working tree after preregistration. Any change requires a new experiment ID and a genuinely new untouched holdout.
5. Use the exact preregistered commit and run `tools/run_preregistered_alpha_experiment.py` once.
6. Immediately before the canonical final runner starts, it computes a holdout identity from **dataset-manifest SHA-256 + exact Final OOS range** and atomically creates `.alpha_consumed/<holdout-identity>.json` beside the dataset manifest. Changing experiment ID, parameters, artifact filename, or report filename cannot reopen that same dataset holdout.
7. If execution crashes after the one-shot claim, the receipt remains consumed. The same holdout is not reopened; a new legitimate untouched range is required.
8. Preserve the generated report SHA-256 and completed consumption receipt as evidence.

## Uncertainty and sample integrity

Synthetic end-of-backtest liquidation is not counted as an organic closed trade for sample-size or expectancy gates.

For organic closed-trade PnL, the report computes a deterministic 95% circular block-bootstrap confidence interval for mean net expectancy. Blocks preserve adjacent trade outcomes rather than pretending every trade is independently distributed. The bootstrap is an uncertainty diagnostic, not a guarantee of stationarity.

The default preregistered acceptance contract requires the **lower 95% block-bootstrap expectancy bound to be positive** once the minimum organic sample is reached. A positive point estimate alone cannot produce `ACCEPT_FOR_LONGER_PAPER`.

## Falsification and verdict

The exact falsification text is generated from `AlphaAcceptanceCriteria` and stored inside the preregistration artifact. The current result vocabulary is deliberately small:

- `ACCEPT_FOR_LONGER_PAPER`
- `REJECT_HYPOTHESIS`
- `INSUFFICIENT_SAMPLE`

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

Until a real final-OOS-eligible dataset is built, preregistered, one-shot consumed, and executed through this protocol, the only valid profitability statement is:

`INSUFFICIENT EVIDENCE`
