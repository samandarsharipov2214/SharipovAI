# SharipovAI Architecture V2: Trading Authority, Learning, and Storage

Status: migration contract. The current paper runtime remains authoritative until
an explicit later migration switches paper authority. Testnet/Mainnet/live
execution are out of scope and remain disabled.

## 1. Authority model

Canonical decision flow:

`Specialists -> Decision Quality -> GC preliminary -> Risk/Portfolio/Security -> GC final -> Execution -> Settlement -> PostTrade Review -> Learning`

### General Controller

General Controller is the single owner of the final trading direction:
`BUY`, `SELL`, or `WAIT`.

It does not invent market evidence and it is not a majority-vote participant.
It synthesizes verified specialist evidence, considers Decision Quality, then
must honor the mandatory gates. A gate cannot create market direction.

General Controller has two explicit stages:

1. **Preliminary intent**: BUY/SELL/WAIT from verified specialist evidence.
2. **Final intent**: BUY/SELL/WAIT after Risk, Portfolio, and Security gates.

Any missing mandatory gate fails closed to WAIT. Risk or Security BLOCK is a
hard veto. Any mandatory WAIT prevents execution for that decision cycle.

### Decision Quality

Decision Quality is advisory. It owns evidence quality, disagreement,
confidence/calibration and rejection of ineligible evidence. It does not own the
final trading direction and never executes orders.

### Risk Engine

Risk Engine owns financial veto and risk limits. Its canonical verdict is
`PASS`, `WAIT`, or `BLOCK`; it must not create BUY/SELL direction.

### Portfolio Engine

Portfolio Engine owns capital availability, exposure, correlation and position
size limits. Its canonical verdict is `PASS`, `WAIT`, or `BLOCK`, with bounded
position constraints. It must not create BUY/SELL direction.

### Security Guard

Security Guard owns policy/safety veto. Its canonical verdict is `PASS` or
`BLOCK` (WAIT may be used while required security evidence is incomplete). It
must not create market direction.

### Execution

Execution has no strategy authority. It may consume only a valid, single-use,
final authorization produced by the canonical decision chain. No V2 shadow
object has execution authority.

## 2. Migration safety

Phase 0 introduces the V2 contract in shadow mode only. Shadow decisions are
recordable/comparable but `execution_authority=False` is an invariant.

A later adapter will feed the same verified evidence to both the current paper
path and General Controller V2. Differences are evidence for migration; they do
not silently change current orders.

Paper authority may switch only after replay/shadow acceptance tests demonstrate
fail-closed behavior, deterministic evidence lineage, correct settlement, and no
regression in safety invariants. Testnet/Mainnet are separate future approvals.

## 3. Outcome semantics and post-trade review

PnL sign is not a market action. A profitable trade must not be rewritten as
`BUY`, and an unprofitable trade must not be rewritten as `SELL`.

Settlement must preserve at least:

- actual entry side and final GC decision;
- entry/exit timestamps and prices;
- gross/net PnL, fees, slippage, drawdown and holding period;
- market regime and verified evidence lineage;
- each specialist recommendation and confidence at decision time;
- Risk/Portfolio/Security verdicts and constraints;
- counterfactual/reference outcome windows used for retrospective assessment.

PostTrade Review asks role-specific questions rather than dividing blame equally.
Examples: market direction/timing for Market Intelligence, event interpretation
for News Intelligence, sizing/exposure for Portfolio, limit adequacy for Risk,
evidence synthesis and WAIT-vs-trade choice for General Controller.

A losing trade is not automatically an agent error. The review distinguishes
strategy error, timing error, sizing error, data/evidence error, execution cost,
regime change, exogenous event, and statistically expected loss.

## 4. Learning lifecycle

Learning may update reputation/metrics from verified outcomes, but a single loss
must never mutate production trading policy directly.

Lessons use a lifecycle:

`candidate -> replay_validated -> shadow_validated -> active`

A lesson that fails replay/shadow validation is rejected or revised. Every
promotion retains evidence, affected roles, before/after metrics and rollback
identity. Learning has no execution authority and cannot weaken Risk, Security,
kill-switch, Testnet/Mainnet, or owner-approval controls.

Counterfactual attribution should estimate whether removing/changing a specific
recommendation would have changed the General Controller decision, instead of
blindly splitting PnL equally across all participants.

## 5. Storage budget

Storage is divided into four classes:

1. **Permanent evidence**: final decisions, settlements, important lessons,
   governance/security/audit evidence. Retained according to explicit policy.
2. **Working state**: current positions, current organ state, recent context.
   Prefer bounded overwrite/compaction instead of append-only growth.
3. **Summarized history**: aggregate high-volume raw observations into useful
   time buckets/statistics before eligible raw data expires.
4. **Ephemeral data**: build cache, temporary files, redundant telemetry and
   bounded logs. Must have size/age limits and safe garbage collection.

A Storage Budget monitor must attribute bytes to Docker images/build cache,
volumes/databases, backups, logs and temporary files. It starts read-only.
Automated cleanup is introduced only for explicitly disposable classes and must
never delete volumes, the running production image, required rollback image, or
canonical evidence without the corresponding retention/backup guarantees.

Deploy must fail before building when safe free-space headroom is insufficient,
rather than discovering ENOSPC after production/deploy state has already moved.

## 6. Acceptance gates for V2 paper authority

Before switching paper authority, tests must prove:

- General Controller is the only final BUY/SELL/WAIT owner;
- advisory/gate agents cannot create direction;
- Risk WAIT/BLOCK and Security BLOCK always prevent a trade;
- missing/stale/unverified evidence fails closed to WAIT;
- position size is bounded by Portfolio and Risk constraints;
- shadow objects can never execute;
- settlement preserves actual trade semantics instead of inferring direction
  from PnL sign;
- post-trade review is idempotent and reconciles financial attribution;
- learning policy changes require validated lesson promotion;
- storage growth and cleanup are bounded without touching production data;
- existing kill-switch/Mainnet/Testnet/live-trading safety invariants remain
  unchanged.
