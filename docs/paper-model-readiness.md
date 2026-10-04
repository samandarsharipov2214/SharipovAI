# Future PAPER evidence readiness

Learning owns the metadata checker; General Controller operations owns its
systemd schedule. It extends the nine-organ architecture and uses the existing
ProjectDatabase. No new decision engine, account, forecast model or database is
created. `docs/paper-next-model-specification.json` freezes the proposed research
procedure. Registration records immutable absolute future dates and the matching
holdout identity in `paper_forecast_readiness/plan`. It does not consume/open the
holdout. Earlier shadow diagnostics and the failed legacy artifact are excluded
from this future final OOS. The existing consumption registry is checked for
overlap, and the continuation must claim the range before any final evaluation.

`deploy/vps/install_model_readiness.sh` installs the timer and two services only
from the deployed checkout, verifies its build and PAPER locks, records the
installation lifecycle in ProjectChangeLedger, and runs one metadata check.
The plan starts at the next UTC day, with 21 training days, seven calibration
days and eight final test days. The extra test day allows seven full days of
timestamp-valid matured support after boundary purging. Feature definitions,
300-second horizon, four-value training-only ridge search, calibration, canonical
costs and all promotion gates are fixed before that future final range exists.
The existing evaluator's relative 60/20/20 split cannot stand in for these dates.

The ordinary Python checker runs at most every six hours. A database cooldown
also covers manual invocations and restarts. Each check reads at most 100,000
physical event row IDs in 5,000-row ranges, with a 90-second deadline and short
reader lifetimes. Incremental canonical state stores metadata counts, pending
anchor timestamps and cursor identities; it stores no prices or return labels.
Row-ID rewrites, regressing cursors, out-of-order source timestamps, changed plans,
missing registry or incomplete scans fail closed. A restored/compacted database
requires explicit cursor reconciliation; it never silently skips history.

Nonoverlapping anchors are reserved before quality checks. Required evidence
includes verified quotes, independently captured feature timestamps, physical
persistence before the horizon, complete captured costs, and a future quote and
independent feature timestamp within 300–310 seconds. Training/calibration labels
crossing the next boundary are purged. Missing anchors remain in coverage.
Readiness requires the whole frozen window, >=28 source days, >=7 test days,
500/200/200 valid labels, >=80% coverage in each split, complete independent
timestamps for verified quotes, >=50 test labels for each supported symbol and
each of the three frozen feature regimes, and no consumed overlapping OOS.

The checker does not train, infer, compute returns, evaluate performance, alter
trading policy, execute orders or call Codex. False conditions produce only a
small JSON status and canonical metadata update. The timer is conditional on
`/root/astra-sharipovai-engineering-DONE`. When readiness becomes true, one atomic
canonical request starts the separate `sharipovai-model-continuation.service`.
The continuation has an additional durable host claim and no timer/restart loop.
A failed launch is an explicit operations failure requiring inspection; it is
not retried every six hours. The existing unconditional Astra watchdog timer is
disabled when engineering completes.

The continuation uses documented [Codex non-interactive execution](https://learn.chatgpt.com/docs/non-interactive-mode)
and the explicitly requested `gpt-6-astra` model. Its prompt is
`docs/paper-model-continuation.md`. Readiness is separate from model promotion
and profitability; every strategy performance gate still applies. Successful
evaluation needs a reviewed immutable artifact binding before PAPER eligibility.

Rollback: disable `sharipovai-model-readiness.timer`; retain canonical plan,
readiness state, holdout consumption and host request claim. Do not remove claims
to obtain another evaluation. Files under `.env.vps` and `CONSTITUTION.md` are
never changed. Tests use disposable databases only and cover delayed/missing
labels, provenance failures, split purging, untouched-range conflicts, cooldown,
single request and physical cursor replacement.
