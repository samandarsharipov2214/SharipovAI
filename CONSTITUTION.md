# SharipovAI Constitution

Version: `2026.07-phase11-production-launch-v16`  
Status: **Binding development and runtime policy**

This document defines non-negotiable rules for research, execution, risk, campaigns,
scaling, evidence, CI, dashboards, security and deployment. A conflicting feature is
invalid even when profitable or operationally convenient.

## 1. Capital protection and compile lock

1. Capital preservation has priority over activity, speed and profit.
2. Mainnet execution is compiled out while `MAINNET_EXECUTION_COMPILED=False`.
3. Environment variables, dashboards, Telegram, LLM output, stored state, experiments,
   reports, schedules, scaling authorities and manual decisions cannot override it.
4. Automated keys must not have withdrawal or transfer permission.
5. Future Mainnet requires a separate audited build, limited subaccount, measured
   Testnet evidence, legal review and expiring owner approval.
6. Martingale, automatic averaging down, leverage increase and all-in allocation are forbidden.
7. Promotion, campaign and scaling records are evidence authority only, never direct
   exchange authority.

## 2. Promotion stages and promotion gate

```text
READ_ONLY -> PAPER -> TESTNET -> CONTROLLED_MAINNET -> SCALE
```

Skipping a stage is forbidden.

- `READ_ONLY`: verified reads without exchange writes.
- `PAPER`: virtual capital and fills over verified market evidence.
- `TESTNET`: bounded writes through `ApprovedExecutionRequest`, durable idempotency,
  authenticated private evidence and reconciliation.
- `CONTROLLED_MAINNET`: unavailable while Mainnet execution is compiled out.
- `SCALE`: never automatic and requires measured evidence plus owner approval.

Promotion is blocked by failed/skipped CI, missing out-of-sample evidence, stale private
streams, fill divergence, data-quality failure, zero-liquidity evidence, orphan data,
duplicate identities, unresolved orders, reconciliation failure or breached loss and
drawdown limits. Failed automated gates cannot be overridden.

## 3. Canonical decision and execution path

```text
Market Intelligence
  -> Portfolio snapshot
  -> Risk Engine hard limits
  -> Correlation-aware capital allocation
  -> Decision Quality
  -> Security Guard
  -> TradingCandidate validation
  -> Paper execution
  -> Campaign authorization where required
  -> Testnet shadow plan
  -> Actual fee/instrument validation
  -> ApprovedExecutionRequest
  -> Durable idempotency reservation
  -> Bybit Testnet executor
  -> Private order topic
  -> Private execution topic
  -> Runtime Fill Harvester
  -> Reconciliation
  -> Final report
  -> Manual decision
```

No dashboard, Telegram handler, Learning Engine, agent, strategy, scheduler, operator CLI
or LLM may call an exchange order endpoint directly. The only write entry is:

```python
BybitExecutionClient.execute(approved_request)
```

## 4. Idempotency and unknown outcomes

1. Every request has deterministic `sai_...` `orderLinkId` from immutable intent.
2. Intent is reserved in `ProjectDatabase` before the network call.
3. The same intent cannot be submitted twice.
4. A timeout after reservation is ambiguous, not a retry signal.
5. Ambiguous requests remain unresolved until authenticated evidence or explicit
   reconciliation resolves them.
6. Startup blocks on missing journal evidence, orphan order/fill, identity mismatch,
   quantity mismatch or unresolved intent.
7. Retry requires a new explicit attempt identity.

## 5. Private order and execution evidence

The read-only private WebSocket must subscribe to both `order` and `execution`.
Private order and execution evidence is canonical:

- `execId` is write-once;
- exact replay is deduplicated;
- conflicting `execId` reuse blocks reconciliation;
- quantity, price, value, time, maker/taker state and actual fees are persisted;
- partial fills aggregate by `orderLinkId`;
- cumulative order quantity equals summed execution quantity;
- execution without private order is orphan evidence;
- executed private order without execution rows is missing evidence;
- stale streams and missing heartbeats block startup and execution.

A fee that cannot be normalized with verified evidence blocks approval.

## 6. Hard risk and correlation-aware sizing

Hard limits override confidence, consensus, expected profit and manual preference.
Mandatory blocks include stale data, kill switch, invalid instrument, loss/drawdown,
exposure/correlation limits, liquidity floor, missing evidence, non-finite values,
expired requests, duplicates, unresolved identities and Mainnet.

Default research/Paper policy:

| Rule | Default |
| --- | ---: |
| Cash reserve | 20% |
| Maximum total exposure | 80% |
| Maximum one position | 20% |
| Maximum correlated group | 35% |
| Maximum risk per trade | 1% |
| Maximum daily loss | 2% |
| Leverage | 1× |

Soft risk may only reduce size: `LOW=1.0`, `MEDIUM=0.6`, `HIGH=0.25`, `CRITICAL=0.0`.

Correlation rules:

1. Missing correlation evidence is not zero correlation; it blocks sizing.
2. Correlations must be finite and within `[-1, 1]`.
3. Duplicate positions aggregate by symbol.
4. Same-symbol exposure reduces remaining position capacity.
5. Correlated exposure reduces remaining cluster capacity.
6. Final notional is the smallest risk, volatility, position, cluster, authority and
   absolute Testnet capacity.
7. Invalid or non-finite input returns zero authorized notional.

## 7. Paper realism and historical-data integrity

Only capital and fills are virtual. Quotes, timestamps, spread, maker/taker fees,
slippage, impact, funding, risk, drawdown and evidence are production-style.
Synthetic prices, fabricated trades and fake catch-up fills are forbidden.

Backtests:

1. process immutable events in `(timestamp, symbol)` order;
2. forbid lookahead, leakage, duplicate bars and random time-series splits;
3. include spread, fees, slippage, impact and funding;
4. share applicable models and risk rules with Paper/Testnet;
5. record configuration, historical manifest identity and commit SHA;
6. require versioned datasets and visible missing intervals;
7. compare buy-and-hold, trend, breakout and mean reversion;
8. require sequential walk-forward out-of-sample evidence;
9. remain evidence, never permission to trade.

## 8. Experiment registry and manual approval rules

Every candidate requires a persistent experiment registry record with immutable ID,
source commit, validated manifest SHA-256, strategy/backtest configuration, walk-forward
results, benchmarks, data validation, Paper summary, fill divergence, automated report
and explicit manual approval or rejection.

The registry is append-only with optimistic versions. Automation may fail closed but may
never change stage, champion, execution flags or deployment.

Manual approval rules:

1. every target requires a current automated report;
2. tokens bind experiment/stage or campaign/report/action;
3. actor and non-empty reason are mandatory;
4. failed automated gates cannot be overridden;
5. approval/rejection is immutable evidence only;
6. approval cannot change flags, credentials, capital, deployment or Mainnet.

## 9. Initial Testnet shadow policy

Paper and Testnet share a source candidate but retain separate observations.

- Initial accepted Testnet notional is **10–25 USDT** per order.
- Dynamic filters, private streams and restart reconciliation are mandatory.
- Historical Paper trades cannot be replayed into a new campaign.
- Mainnet execution is compiled out.

A completed campaign requires:

| Gate | Requirement |
| --- | ---: |
| Matched Paper/Testnet fills | 20+ actual matched fills |
| Unmatched Paper fills | 0 |
| Unmatched Testnet fills | 0 |
| Orphan evidence | zero orphan |
| Duplicate/conflicting identities | 0 |
| Unresolved intents | 0 |
| Actual private execution fees | Present |
| Private streams | Fresh and authenticated |
| Reconciliation | Restart-safe |

A sample below 20 remains running, never successful. A campaign row, screenshot, copied
JSON or Paper-only fill is not private execution proof.

## 10. Scheduled campaigns and single authorization

1. Scheduler uses only experiments manually approved for `testnet`.
2. State is persisted in `ProjectDatabase`.
3. Worker is disabled by default.
4. At most one global non-terminal campaign authorization exists.
5. A schedule creates bounded authorization, not raw-order authority.
6. Authorization binds campaign ID, experiment ID and scope.
7. Trades before activation cannot attach to the campaign.
8. Failures are persisted and never blind-retried.
9. Scheduler cannot change runtime flags or Mainnet availability.

## 11. Immutable Phase 9 reports

1. Campaign results use evidence-derived `report_id` and append-only storage.
2. A separate index may point to the latest report but cannot replace history.
3. Report SHA covers campaign/analysis identity, metrics and trades.
4. Scaling rejects corrupted or non-finite report evidence.
5. Multiple reports from one campaign count as one campaign.

## 12. Controlled scaling authority

A Phase 10 authority requires:

1. eligible SHA-256 protected Phase 9 plan with no failed gate;
2. at least two distinct clean campaigns;
3. finite current/proposed notionals;
4. increase no greater than `1.5x`;
5. absolute Testnet ceiling at most `50 USDT`;
6. exact confirmation `I_APPROVE_CONTROLLED_TESTNET_NOTIONAL_SCALING`;
7. canonical authority hash bound to the plan hash;
8. one persistent global optimistic lock;
9. scope and finite expiration;
10. Testnet environment, canonical execution path, no kill-switch override and Mainnet false.

Expired, revoked, tampered, non-finite or lock-mismatched authority fails closed.
Partial persistence/audit failure changes authority and lock to `aborted`. Scaling is
never automatic.

## 13. Performance evidence

1. Phase 9 reports create immutable Phase 10 snapshots.
2. Snapshot SHA covers stable timestamp and metrics.
3. Exact replay is idempotent; conflicting identity reuse is forbidden.
4. Monthly reports verify every snapshot before aggregation.
5. Monthly reports use evidence-derived IDs and retain history.
6. Net PnL, fees, matched fills and maximum drawdown are mandatory.
7. Drawdown breach creates a critical alert and failed result.
8. No-fill month remains visible and cannot be called successful.

## 14. First real bounded Testnet campaign

A real campaign requires complete current-head CI, exact deployed SHA, clean post-deploy
audit, isolated Testnet credentials, no Mainnet credentials, private `order` and
`execution` health, restart-safe reconciliation, approved experiment, zero active
campaigns, zero scaling authorities and an explicit finite operator window.

Pre-deploy audit is not campaign permission. After bounded Testnet runtime deployment,
`scripts/phase11_first_campaign_checklist.py` must return:

```text
ready = true
failed_checks = []
campaign_started = false
mainnet_enabled = false
```

The checklist is read-only. Actual start remains a separate operator action. Completion
requires 20+ actual matched private fills, actual fees and zero orphan, duplicate,
unmatched, conflicting or unresolved evidence.

## 15. Operator control plane

`scripts/testnet_campaignctl.py` is the operator control plane over canonical services.

- `snapshot` and `plan` are read-only.
- `start`, `cycle`, `report` and `decision` require distinct confirmations.
- It cannot set environment variables, install credentials, disable the kill switch,
  submit raw orders, deploy code or enable Mainnet.
- Report generation is idempotent for unchanged evidence.
- Campaign decisions bind campaign ID, report ID and action.

## 16. Final report and manual decision

The final report combines experiment identity, campaign metrics, fill divergence,
private stream health, startup/execution reconciliation, actual fees and zero
identity-failure gates. It stores evidence SHA-256 and returns only
`eligible_for_manual_decision` or `blocked`.

Automatic report generation never removes the separate manual decision. A blocked
report cannot be approved.

## 17. Dashboard and API security

1. Sensitive Phase 9–11 routes require an active administrator.
2. Authorization occurs before request body parsing.
3. Models reject extra fields, invalid symbols and non-finite floats.
4. Dashboard uses safe DOM APIs, not `innerHTML`, `insertAdjacentHTML` or `eval`.
5. Live requests require timeout, cancellation, visibility awareness and backoff.
6. Missing/stale data is unavailable or blocked, never invented.
7. Dark/light/system themes, mobile layout, focus and reduced motion are mandatory.
8. Responses require MIME-sniff, clickjacking, referrer and permissions protection;
   HSTS is emitted only on HTTPS.
9. Dashboard cannot change the Mainnet compile lock or start a raw order.

## 18. Production audit, deployment and rollback

Production readiness requires:

- canonical checkout `/opt/sharipovai-repo`;
- immutable approved full SHA and clean worktree;
- dependency audit, compilation, full pytest and dedicated crash suite;
- compile/runtime Mainnet lock and engaged production-safe kill switch;
- auth enabled, database required and sandbox mode;
- canonical SQLite/PostgreSQL health;
- tracked secret-file hygiene;
- atomic post-deploy evidence with deterministic SHA-256;
- persistent monthly monitoring;
- verified first-campaign launch checklist;
- exact-SHA rollback to a reviewed ancestor.

Rollback requires `I_APPROVE_PHASE11_EXACT_SHA_ROLLBACK`, deployment lock, current-release
backup, target preflight, financial-lock verification, health/smoke checks and automatic
restoration of the original SHA if the target fails.

The deterministic audit hash excludes timestamps and host metadata. Identical audited
state must produce identical SHA-256 evidence.

## 19. CI cleanroom and crash rules

Merge requires dependency install, `pip check`, `pip-audit`, compilation, hard Mainnet
lock, execution/idempotency/reconciliation tests, private evidence tests, campaign tests,
research audits, complete pytest, Phase 9–11 hardening, retained artifacts and rollback.

CI cleanroom runs before imports and:

1. verifies kill switch and disabled execution flags;
2. rejects production exchange mode/base URL;
3. deletes only explicit SQLite/WAL/journal/runtime paths;
4. permits deletion only in workspace or `/tmp`;
5. refuses broad discovery and unsafe roots;
6. retains JSON evidence;
7. fails collection on violation.

Failures are classified as `regression`, `stale_test` or `environment_contamination`.
Classification cannot convert a failed, missing, cancelled, queued or skipped workflow
to green.

Mandatory crash scenarios include restart, timeout, database failure, malformed payload,
duplicate identity, non-finite data, stale streams, expired authority, corrupted evidence,
concurrent activation, partial event persistence, wrong deploy root, failed rollback and
SHA mismatch.

## 20. Database, evidence and secrets

`ProjectDatabase` is the canonical source for experiments, reports, schedules, campaigns,
decisions, intents, private state, reconciliation, validation, scaling, performance,
audit and project memory.

Secrets, keys, seed phrases, credentials and tokens are forbidden in Git, logs, metrics,
experiments, reports, test artifacts and documentation examples.

## 21. Profit and user claims

SharipovAI reports measured results after all modeled and available actual costs. It must
not promise guaranteed income, fabricate performance or scale capital based only on a
backtest, confidence score or narrative.

## Change history

| Version | Date | Summary |
| --- | --- | --- |
| `2026.07-phase11-production-launch-v16` | 2026-07-19 | Canonical checkout, exact-SHA preflight/post-deploy/rollback, machine first-campaign gate, security headers and expanded crash contracts. |
| `2026.07-phase11-deep-audit-v15` | 2026-07-19 | Scaling integrity, correlation fail-closed sizing, immutable performance history and deterministic audit. |
| `2026.07-ci-cleanroom-testnet-operations-v9` | 2026-07-16 | CI cleanroom, bounded operator CLI and first-real-Testnet runbook. |
| `2026.07-scheduled-execution-evidence-v7` | 2026-07-14 | Scheduled orchestration, private evidence and bounded campaigns. |
| `2026.07-research-promotion-v4` | 2026-07-14 | Versioned data, funding/impact modeling, walk-forward evaluation and benchmarks. |
| `2026.07-execution-research-v3` | 2026-07-14 | Durable idempotency, reconciliation, hard risk and event-driven backtesting. |
| `2026.07-safety-foundation-v2` | 2026-07-14 | Mainnet compile lock, canonical execution request and truthful CI. |
