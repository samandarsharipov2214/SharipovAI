# Alpha validation block ledger — 2026-08-12

| Block | Status | Evidence |
|---|---|---|
| Historical provenance | DONE | Loader emits `price_source`, `interval_ms`, `timestamp_semantics`; close-derived review requires `bar_close`. |
| Same-bar timing | DONE | `EventDrivenBacktester` defers synthetic-close signals to the next same-symbol event, before new strategy evaluation. |
| Preregistration | DONE | `AlphaExperiment` fingerprints immutable strategy/data/cost/risk/range configuration and rejects an overlapping final holdout. |
| Candidate selection | BLOCKED_EXTERNAL | No canonical historical dataset manifest or verified data file is present in the repository. No OOS range can be frozen honestly. |
| Walk-forward/OOS verdict | BLOCKED_EXTERNAL | Depends on the missing manifest and verified immutable dataset above. |
| Paper campaign | BLOCKED_SAFETY | Cannot start a new strategy campaign before a passing final-OOS research gate. |

The current honest trading conclusion is **INSUFFICIENT EVIDENCE**, not a
profitability estimate.  The precise unblocker is one canonical public-data
dataset accompanied by a SHA-256 manifest, gap/duplicate report, explicit
`timestamp_semantics`, and an untouched final OOS range.
