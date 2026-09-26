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
