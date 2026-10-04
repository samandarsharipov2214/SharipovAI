# Prospective PAPER intelligence — release evidence

Base: `3f03c805991531e572e0d674d555874b3df5cb2c`. This continues the
existing trading-intelligence worktree. No exchange execution is authorized.
The release is a **shadow producer**, with no reviewed execution model.

## Findings and boundaries

The v1 containment correctly rejected every entry because it had no typed,
validated prospective return. Historical movement, impact-derived confidence,
Council votes and historical mean markouts cannot substitute for that return.
Additional observed defects were collection time used as news freshness,
neutral relevance scores acquiring positive polarity, shared news being counted
through multiple child agents, and repeated reads of unchanged Learning history.

`ai_architecture_registry.responsibility_owner()` identifies Market for trend
features, Learning for research, Decision Quality for consensus, and Virtual
Execution for paper fills. This change extends those owners. It creates neither
an organ, database, exchange transport nor competing decision runtime.

| Organ | Runtime, inputs → outputs / persistence / consumers | Authority and observability |
|---|---|---|
| General Controller | `GeneralControllerV2`, Council evidence and gates → `paper_v2_decisions` → canonical runtime | Final direction; synchronous within live PAPER worker. Legacy provider directive remains migration evidence. |
| Market Intelligence | Shared public WS, REST BBO/24h features and multi-exchange verification → exact `council_market_evidence`, prospective forecast → Council/PAPER | Evidence only; public worker and independent feature/quote timestamps. No guessed quotes. |
| News Intelligence | Source workers → `news_memory`, article/fetch lineage → one canonical Council news voice | Advisory direction, no execution. Publication and collection remain distinct; future/unknown/archive/unverified inputs abstain. |
| Risk Engine | `CanonicalRiskService`, market/account state → `risk_assessments`, V2 gates, post-stop memory | Veto only. Missing evidence blocks. Existing post-stop observe policy is preserved. |
| Portfolio Engine | Account state and dynamic instrument/cost rules → `portfolio_snapshots`, `autonomous_paper_state` | Solvency and sizing, no V2 direction. Fee/spread/slippage/impact costs retained. |
| Virtual Execution | `CanonicalPaperDecisionRuntime`, validated candidate and economics → durable intent, consumption, `paper_trades:<scope>`, settlements | Single canonical PAPER consumer; restart recovery and single-use identities preserved. |
| Decision Quality | Exact Council opinions → persisted quality assessments / candidate bridge | Advisory quality/agreement only. Cannot override GC direction or vetoes. |
| Learning Engine | Verified settlements joined by exact decision ID to entry/build/policy trades; observer opportunities → outcomes, shadow cohorts, immutable forecast artifact | Worker plus asynchronous observer; negative net outcomes retained. No self-promotion. |
| Security Guard | PAPER environment/candidate checks, persistent execution lock, global authentication | Veto; kill switch ON, all exchange write paths OFF. |

All use the existing ProjectDatabase. Runtime monitor observations are persisted
per organ. Synchronous organs do not claim separate background threads. A failed
probe now leaves the other eight observable; stale observations are degraded
instead of gaining a new health timestamp when read. PAPER status and the organ
monitor use the existing nonblocking snapshot path when the execution lock is busy.

## Forecast and promotion contract

`paper-return-forecast-v1` identifies an immutable forecast by SHA-256, symbol,
as-of, feature cutoff, generation/expiry, 300-second horizon, producer/model hash,
training window, support, validation report hash and exact quote lineage.
The producer is `quote-ridge-300s-v1`. Inputs are 24h return, relative BBO spread
and log turnover. These are predictors, never direct economic edge aliases.

Units are **gross midpoint simple return fraction**. Prediction uncertainty is a
95% nominal absolute-residual radius calibrated on a separate chronological
period; conservative return is prediction minus that radius. Serial dependence
means this empirical interval is not an IID coverage guarantee.

At entry, `conservative_return_fraction * quantity * midpoint` gives USDT edge.
It must strictly exceed **1.5 × (fees + spread + slippage including impact)**.
The final check repeats at the exact instrument-rounded executable size. Impact
calculation errors veto instead of retrying with volume removed. First entries
and re-entries share this requirement; same-decision re-entry remains blocked.
A qualified entry carries its forecast ID/model and horizon into durable intent,
position and both trade legs. Existing protective exits remain active; a position
supported by a 300-second forecast also expires at that forecast's horizon.

Promotion requires both objective validation and a reviewed code change binding
the **entire immutable artifact hash** in `REVIEWED_MODELS`. That set is empty.
Database flags, file existence and Learning scores cannot grant authority. The
service cannot submit orders; even promoted evidence still needs the complete
GC → Risk/Security → Portfolio → candidate → canonical PAPER path.

Validation gates include complete source coverage, explicit as-of feature
timestamps, global label purging, sealed untouched holdout, 500/200/200 minimum
train/calibration/test support, 28 days of source data, seven test days, 80%
coverage, improvement over zero-return and training-mean baselines, directional
accuracy ≥52%, interval coverage ≥90%, limited bias, 50 positive cost-adjusted
actionable observations, three stable chronological folds, and adequate stable
symbol/regime groups. These are necessary engineering gates, not profitability
claims. Malformed/nonfinite reports or unsupported symbols fail closed.

## Sealed historical experiment — no promotion

The previous session sealed and evaluated one bounded export before quota ended.
It is preserved unchanged; we did not tune on or re-evaluate its final holdout.

- Scope: `2ba720c9995d8d3653ba`; cutoff: `1790005640434` UTC milliseconds.
- Source: 481,768 canonical opportunities; complete through the cutoff.
- Export SHA-256: `f520328b0ebe7b484acc35f604cbf4fcfb5b4015691ed123f689f4f83209d6af`.
- Artifact canonical digest: `1db9e8a2c657a9203c69cfa38ea2c440857f931b699023083453d9d8c4ae1e97`.
- Fixed ridge specification, no hyperparameter search; common chronological
  60/20/20 boundaries across all symbols, with labels physically available
  strictly before the next period. Expanding-window folds precede calibration.
- Non-overlapping per-symbol anchors are reserved before label checks. Missing
  labels remain in coverage; they are not replaced with later winners.
- 8,095 training, 1,862 calibration, 2,557 test labels; 11.4476 source days and
  2.2895 test days. Test coverage 90.3214%.
- Test MAE 0.00122916 versus zero baseline 0.00122767 and training-mean baseline
  0.00122886; RMSE 0.00175638 versus zero baseline 0.00175543.
- Directional accuracy 47.6513%; interval coverage 92.8432%; **zero actionable
  holdout observations** after the conservative cost cushion.

This fails duration, baseline, directional, actionable-support, fold and
symbol/regime stability gates. Historical captures also lack an independently
stored REST feature timestamp; the new promotion contract explicitly requires
that evidence. The sealed artifact retains its original diagnostics and limitations,
including its old approximate cost proxy. Future evaluations use the same canonical
BUY/SELL cost formula and midpoint denominator for both return and costs; their
results must not be represented as a re-run of the original untouched experiment.
The corrected evaluator is versioned `purged-forecast-validation-v2`; it also
checks independent future REST/BBO timestamps against the horizon. Impossible
losses, probabilities and sample counts cannot pass its promotion checks.
The evaluation CLI now uses the existing canonical holdout-consumption registry,
keyed by opportunity scope and time range. Renamed/re-exported files cannot
reopen an overlapping holdout; the prior sealed artifact's range remains consumed.
Claims are recorded before evaluation and remain consumed if evaluation fails.

New runtime observations preserve the REST feature timestamp and full cost-model
parameters. Forecast IDs are linked to the existing opportunity observer; its
fixed-horizon labels remain the single forward-outcome source. No new competing
outcome ledger is created. Forecast coverage counts proposals reaching inference,
and is distinct from actionable coverage and successful execution coverage.

More time alone will not solve the failed loss/stability tests. Under the fixed
60/20/20 specification, seven test days require at least 35 total days. Any
revised model needs a new untouched chronological holdout and an explicit review;
the already inspected holdout cannot be relabeled untouched for model selection.

## News and repeated work

Council uses source publication time, requires known nonfuture collection and
persistence, preserves declared polarity, and deduplicates exact links/event
identities both within and across child-agent views. Syndicated links are not
proof of independent sources. Unique child evidence produces one News Intelligence
voice with `independence_status=NOT_ESTABLISHED`. Broad category matching remains
imperfect symbol relevance and is explicitly not a calibrated return predictor.

The 500K counter is cumulative across restarts, not a count of trades or current
process iterations. The preserved snapshot had 502,004 suppressed WAITs; a later
runtime observation had 507,764, with zero new executions. The observer was alive,
with 49,550 rows recorded in that process, zero dropped/failed and an empty queue.
Measured CPU varied (30–69% in brief samples); cumulative I/O is not a write rate.

Changes preserve tick/quote responsiveness and protective exit checks. Provider
schedule reads are cached per symbol; unchanged interval traces no longer rewrite
the last economic rejection. Observer history is reused only while exact source
count/version/time watermarks and equivalence events are unchanged. Each assessment
still applies its own as-of cutoff. Process cycle duration, suppression rate and
observer cache hits make this measurable. Existing bounded WAIT signatures,
storage retention, archive-before-delete and reversible compression remain intact.
No manual WAL/SHM deletion, database rebuild or account reset is used.

## Accounting, testing and acceptance

The pre-release capture reconciles 2,186 executions / 1,093 settlements across
both PAPER scopes, with no orphan pairs, settlement PnL mismatches or missing
Learning outcomes. The recent `e4ec31c2...` cohort remains separate: 39 closes,
20 wins / 19 losses, +1.7583191883 USDT net, 0.5743213117 fees and profit factor
1.71636. Its evidence is retained; it is not proof of future profitability.
Legacy, active-scope, policy/build, new-producer and post-deployment cohorts are
reported separately. Return/drawdown remain unavailable without the corresponding
capital/equity history; they are never inferred from a convenient denominator.

Focused tests cover schema, units, mismatches, stale/future features, uncertainty,
provenance, malformed validation, no self-promotion, purged splits, untouched model
fit, missing/low edge, exact cost rounding, first entry, duplicate execution,
horizon exit, real GC ownership and Risk/Security/Portfolio vetoes, losing
settlement → Learning, news freshness/polarity/syndication, source-cache invalidation,
database failure, history reconciliation and isolated/stale worker observations.
Existing PAPER recovery, re-entry, cost, settlement, Learning and storage suites
remain release gates. Full required suites run on the exact PR and main commits
in hosted CI; the production host only runs bounded focused tests.

Production acceptance uses `scripts/paper_intelligence_acceptance.py`, never the
bounded JSON account cache as lifetime truth. Capture before/after; compare every
old execution/settlement hash; reconcile both scopes, open positions, cash/equity,
realized PnL, fees, Learning and pending intents. Fail on shrinkage, changed records,
orphans, accounting mismatch or unreconciled intents.
Pre/post cash changes must also equal immutable execution cashflows. Updating
cash and equity together without executions cannot hide an account reset.

Deployment uses `deploy/vps/update_from_main.sh` with the exact approved main SHA,
clean checkout, verified canonical backup, disk preflight and retained rollback
image. Verify main/checkout/build/OCI equality, stable healthy container, local and
public HTTP 200, all nine organs, fresh PAPER updates, forecast shadow status and
every owner-required safety flag. Canonical rollback restores the retained image
without deleting additive evidence or resetting accounts; a source revert also
restores the prior unavailable-edge containment.

Profitability remains unproven. The unchanged operational gate needs ≥50 genuinely
new closed trades over ≥7 days, wins > losses, positive net PnL/expectancy/return,
profit factor ≥1.20, drawdown ≤5%, no accounting/safety/look-ahead defect and no
single abnormal winner dominating the result. Shadow forecasts and OOS diagnostics
cannot satisfy that gate. No trades will be manufactured to meet it.

## Release review — 27 September

The exact-packet runtime regression exposed a lifecycle mismatch: optional
forecast access assumed `__init__` had run, and tick finalization then masked that
error with an uninitialized cycle counter. Optional inference now has an explicit
unavailable default. Normal construction eagerly initializes process telemetry;
partial/recovery construction initializes it once before ticking or reading
metrics. Persisted suppression counts are excluded from the new process rate.
Failed ticks still count and retain their original error. Nonblocking status
retains these scalar metrics while execution holds its lock. No required trading
dependency or authorization is synthesized.

Full-diff review also tightened two provenance boundaries. Forecast validation
now binds the exact Council decision as-of separately from quote identity and
freshness. The evaluator no longer accepts an untouched-holdout boolean: it must
consume a range in the canonical registry before evaluating labels, then bind
the completed claim to the report hash. Failed attempts remain consumed.
Promotion and execution both require that matching completed canonical receipt;
reviewing an artifact hash cannot override a missing, changed or incomplete
receipt. Unsealed research remains explicitly ineligible. The preserved original
failed artifact has not been refitted, relabeled or promoted.

Acceptance now checks unmatched BUYs and open quantities in older PAPER scopes
as well as the active scope. Fresh pre-release ProjectDatabase evidence still
contains 2,186 executions and 1,093 settlements, with no orphans, PnL/Learning
mismatches, pending intents or account discrepancies. Local and public health
both returned HTTP 200; all exchange write paths remained locked.

Focused lifecycle/provenance/acceptance checks passed, including the original
exact-packet regression, unavailable-producer BUY containment, failed-tick
telemetry, repeated/failed holdout consumption, forged receipt rejection and
exact-as-of mismatch. All 932 tracked Python sources compiled, critical imports
and hard execution locks passed. The complete suite and exact-head GitHub CI
remain mandatory release gates; test fixtures never become production evidence.

## Resume verification — 28 September

The existing local changes were retained. The original exact-packet regression
and the requested ordered lifecycle, forecast, Council, PAPER, acceptance, news,
authority/veto and settlement/Learning suites pass (286 test executions). Fresh
canonical acceptance still reconciles 2,186 executions and 1,093 settlements,
with zero orphans, quantity/PnL/Learning discrepancies, open positions or pending
execution intents. The historic failed holdout remains unchanged and unpromoted.

Deployment review found that the canonical updater used hard resets and changed
environment-file permissions. It now requires a fast-forward release, verifies
the exact checkout SHA and uses a detached previous checkout for retained-image
rollback, without modifying `.env.vps`. Real-Git fixtures verify successful
deployment, rollback, preservation of divergent local work and unchanged private
environment content/mode/time; 104 focused deployment checks pass. The pending
executable mode of the backup verifier is carried into this PR as well.

Release remains conditional on exact-head CI, a fresh verified canonical backup,
healthy PAPER-only deployment and post-deployment reconciliation. A busy SQLite
checkpoint is reported as busy; it cannot justify manual WAL/SHM deletion.

## Production acceptance follow-up — 29 September

PR #469 merged at `19e6c8e6e469864921edda752872cc298056ffdc` after all seven
head checks and the six applicable merged-main checks passed; the full suite had
2,724 passing tests. The canonical updater deployed that exact SHA. Fresh checks
confirmed checkout/build/OCI identity, healthy runtime, both HTTP health routes,
unchanged protected files and all financial locks. Canonical history still has
2,186 executions and 1,093 settlements, with unchanged hashes, reconciled cash,
zero orphans/mismatches, no open positions and no new executions. Over 1,500 real
SHADOW forecasts passed independent timestamp, quote and digest checks.

Live acceptance exposed a remaining integration mismatch: the provider stores
the captured quote time in `market_timestamp_ms`, but forecast validation received
the later proposal `received_timestamp_ms`. The corrected call uses quote time;
as-of, expiry, independent REST feature time and all promotion checks remain
mandatory. Regression coverage reproduces a delayed packet, still rejects a
different quote and keeps unpromoted evidence blocked. Synthetic reviewed models
exist only in tests. The original failed holdout is also registered as consumed
in production without reevaluation or a promotable v2 receipt.

The successful deployment backup left a 2.37 GB WAL allocation available for reuse.
Later automatic checkpoints reused that allocation, and the scheduled exporter
correctly refused the aggregate source above its existing 20 GiB restore gate.
Canonical SQLite connections now set a 64 MiB retained-journal limit. SQLite
reclaims excess allocation only when the WAL safely resets; active readers and
uncheckpointed data can exceed that size. A real SQLite regression keeps an old
reader alive across a larger committed transaction, proves its snapshot remains
valid, then verifies the normal reset releases space while every row survives.
There is no manual sidecar deletion, forced checkpoint, history deletion, schema
change or relaxed backup floor. See the
[SQLite journal-size contract](https://www.sqlite.org/pragma.html#pragma_journal_size_limit).

These acceptance corrections continue on the same trading-intelligence branch;
the already merged PR is preserved. Their exact-head CI and canonical redeployment
acceptance are separate requirements before the watchdog completion marker.

## Final mission inspection — 4 October

Remote main remains `7bfc9b66dd71bc745b7a5b581af4d77f46fb846e`; the production
checkout/build/OCI remains `19e6c8e6e469864921edda752872cc298056ffdc`. The worktree
and production checkout were clean. The original 3,279 trade/settlement content
hashes are unchanged, all 2,186 executions reconcile, and all financial locks
remain enabled. Database quick_check returned `ok` after 957.77 seconds. The
42 delayed-lineage and retained-WAL focused tests pass.

The fresh exact-main full-suite run
[37182954469](https://github.com/samandarsharipov2214/SharipovAI/actions/runs/37182954469)
found one failure among 2,730 tests: a cabinet test searched the entire payload
for the word "demo", which appeared in a real news headline. The regression now
uses an isolated headline containing that word and checks the actual canonical
account authority fields. Production news content is preserved.

Live organ observations were stale because the monitor sorted lifetime Risk,
Portfolio and Decision Quality history every cycle. SQLite query plans confirmed
temporary sorts despite LIMIT 1. Exact current Council trace identities already
reference these immutable records. Following all five current decisions took
0.054 seconds on the same production database. The monitor now uses those exact
keys and event entity IDs, preserving original evidence timestamps and reporting
missing or stale current evidence. No schema migration or new hot-path index is
needed. Callers remain the safe installer, runtime/system health, watchdog and
authenticated organ endpoints. Tests verify bounded identity reads, stale and
missing evidence, per-organ failure isolation and unchanged authority.

The [readiness mechanism](paper-model-readiness.md) and
[frozen next-candidate specification](paper-next-model-specification.json) keep
future evidence waiting outside Codex. Its tests cover provenance, missing labels,
global boundary purge, source cursor integrity, six-hour cooldown and one request.
Neither readiness nor this infrastructure change promotes the failed artifact.

Deployment remains gated on a fresh canonical backup and verified recovery
capacity. Inspection found a 1.975 GB retained WAL, a roughly 21.407 GB canonical
database and approximately 23.1 GB free. The persistent source now exceeds the
exporter's 20 GiB admission budget even excluding WAL/SHM. The prior successful
archive is dated 29 September. The full isolated restore admission needs about
32 GB, above available workspace. This PR does not relax either limit, delete
history, force a checkpoint or edit production files to bypass release tooling.
Rollback remains the retained previous OCI image and canonical updater; readiness
rollback disables its timer while preserving its plan and one-shot claims.

## PR 470 review follow-up — 4 October

Readiness now counts the full frozen window's expected anchors, including
unpersisted observation gaps. Incremental state and the plan bind the checker
version and source hashes. Completed scan batches survive deadline interruptions.
Canonical integral-float quote timestamps use the same validator as forecasts;
bools, strings, fractional and nonfinite timestamps remain invalid. The host
installer records failed mutations, uses the wrapper lock before activating its
timer, and preserves checker error output and exit codes. Tests exercise these
failure paths with disposable databases and mocked host commands.

The dependency audit identified PyJWT 2.13.0 vulnerabilities. Its exact pin is
updated to 2.15.1; upstream fixes are documented in the
[PyJWT changelog](https://pyjwt.readthedocs.io/en/stable/changelog.html).
Authentication regression tests and exact-commit CI remain mandatory.

The source database has grown beyond the existing 20 GiB backup admission limit.
The VPS has no second disk, and available workspace cannot satisfy the backup
and isolated-restore requirements. This is a release blocker, not authorization
to skip backup, weaken integrity, delete history, or mark engineering complete.

The reviewed backup capacity correction raises the shared, bounded source,
archive and restore admission envelope to 32 GiB. Source identity checks,
streamed size limits, manifests and hashes, safe path checks, database
quick_check, the 20 GiB exporter free-space floor, the 512 MiB extra reserve,
and the isolated restore's 2 GiB runtime reserve remain mandatory. Logical
restore reserves up to 1.5 times database size (capped at the envelope), so the
larger envelope does not authorize using this VPS's insufficient workspace.
Backup/restore clients must use the matching reviewed tooling. Sparse-file and
mock-export tests cover a 22 GiB source and rejection above 32 GiB without
allocating that volume in CI. No production history is compressed or deleted.

## Final PR 470 review follow-up — 4 October evening

All current Council decision identities must resolve before Risk, Portfolio or
Decision Quality can report healthy evidence. Freshness uses the oldest current
assessment, so one fresh symbol cannot hide another symbol's stale record.
The bounded readiness checker now fixes its physical event watermark before
reading the validation clock; concurrent later writers remain for the next cycle.
The host installer refuses dirty tracked/staged/untracked inputs before mutation,
rechecks the checkout, and compares installed units to the committed Git blobs.
Native archive extraction, restore copying and restore drills preserve the same
2 GiB runtime reserve with admission and per-write free-space checks. Logical
restore's existing larger workspace gate remains unchanged.

The live evening reconciliation again preserves all 3,279 trade/settlement hashes:
2,186 executions, 1,093 settlements, no orphans, PnL/Learning mismatches, accounting
issues, open positions or pending executions. Canonical active cash remains
100.18884118560003 USDT. Production is still on `19e6c8e6`, with the kill switch,
sandbox and PAPER enabled and every exchange execution bridge disabled.

The latest completed descriptive research contains 34,274 real SHADOW forecasts
over 5.4215 source days, with 32,071 valid 300-second labels (93.57% coverage).
The 810,918 earlier observations have no independent feature timestamps and are
excluded from prospective promotion evidence. Of 264,255 later observations,
263,885 verified quotes carry that timestamp. There are 6,625 valid nonoverlapping
labels. Among 34,382 joined flat-account Council decisions, 11,821 (34.38%) have
final bearish intent. The 11,307 bearish decisions with labels have mean short
proxy return -0.2575% after exchange costs, before borrow/funding/liquidation
costs. These data support retaining spot long-only behavior. The opened diagnostic
cohort remains ineligible for the frozen future final OOS; no model is promoted.

The current process reports five-second cadence, zero dropped/failed observer
batches, 52,962 metadata cache hits and one source refresh across 52,963 cycles.
Persisted organ evidence is stale under the old lifetime-sorting monitor, which
is why the bounded monitor correction still requires production deployment.
Backup/restore workspace remains the external release prerequisite. No completion
marker is justified until the exact final main is deployed and accepted.
