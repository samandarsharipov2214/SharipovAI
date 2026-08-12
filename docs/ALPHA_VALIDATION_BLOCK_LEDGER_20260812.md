# Alpha validation block ledger — 2026-08-12

| Block | Status | Evidence |
|---|---|---|
| Historical provenance | DONE | Loader emits `price_source`, `interval_ms`, `timestamp_semantics`; close-derived review requires `bar_close`. Files: `historical_data/{manifest,loader}.py`, tests: historical/timing suite 17 passed, commit `a4e1f863`. |
| Same-bar timing | DONE | `EventDrivenBacktester` defers synthetic-close signals to the next same-symbol event, before new strategy evaluation. Files: `trading_core/{backtest,models,strategy_suite}.py`, tests: timing suite 17 passed, commit `a4e1f863`. |
| Preregistration | DONE | `AlphaExperiment` fingerprints immutable strategy/data/cost/risk/range configuration and rejects an overlapping final holdout. Files: `trading_core/alpha_experiment.py`, tests: 17 passed, commit `f19a4280`. |
| Signed funding accounting | DONE | Negative funding is a valid credit rather than a corrupt negative cost. Files: `trading_core/strategy_suite.py`, tests: funding/paper suite 12 passed, commit `dd4bcc18`. |
| Candidate selection | BLOCKED_EXTERNAL | No canonical historical dataset manifest or verified data file is present in the repository. No OOS range can be frozen honestly. |
| Walk-forward/OOS verdict | BLOCKED_EXTERNAL | Depends on the missing manifest and verified immutable dataset above. |
| Paper campaign | BLOCKED_SAFETY | Cannot start a new strategy campaign before a passing final-OOS research gate. |

The current honest trading conclusion is **INSUFFICIENT EVIDENCE**, not a
profitability estimate.  The precise unblocker is one canonical public-data
dataset accompanied by a SHA-256 manifest, gap/duplicate report, explicit
`timestamp_semantics`, and an untouched final OOS range.
