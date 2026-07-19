# Phase 11 — Deep Audit, Crash Validation and Production Hardening

## Executive status

Phase 11 is an integration and hardening release built from the current `main`. The previous Phase 11 branch had diverged from `main`; its Phase 10/11 files were not assumed to be deployed or production-ready.

Mainnet remains compiled out. Automatic campaign launch remains disabled. A real Testnet campaign is not claimed until deployment, private stream evidence and campaign fills exist on the approved commit.

## Audit results

| Area | Finding before hardening | Severity | Resolution |
| --- | --- | ---: | --- |
| Branch integrity | Phase 10/11 were absent from current `main`; old Phase 11 was behind newer CI/documentation fixes | Critical | Clean integration branch created from current `main` |
| Scaling numbers | `NaN` and `Infinity` could bypass ordinary numeric comparisons | Critical | Finite-number validation added to policy, plans, authority and API models |
| Scaling integrity | Authority hash was created but not verified before use | Critical | Canonical SHA-256 validation required on every authority check and revoke |
| Scaling concurrency | Parallel activation could create more than one active authority | Critical | Persistent global optimistic lock added; only one activation wins |
| Scaling expiry | Dashboard counted records with `status=active` even after expiration | High | API now exposes only valid, unexpired, integrity-checked authorities |
| Monthly history | Reports used the month as a mutable key and could overwrite negative history | Critical | Evidence-derived immutable report IDs and append-only history added |
| Snapshot corruption | Monthly aggregation trusted supplied snapshot bodies | Critical | Every snapshot hash is verified before aggregation |
| Correlation risk | Missing correlations were treated as zero correlation | Critical | Missing and invalid correlation evidence now blocks sizing |
| Same-symbol exposure | Existing exposure in the proposed symbol was not deducted correctly | High | Same-symbol exposure is aggregated and deducted from position capacity |
| API parsing | Sensitive bodies could be parsed before endpoint authorization | High | Phase 10/11 prefixes added to early admin middleware guard |
| API validation | Raw dictionaries allowed extra fields and non-finite floats | High | Strict Pydantic models reject extra and non-finite data |
| Audit integrity | Audit hash included changing timestamps, so identical state produced different hashes | Medium | SHA-256 now covers deterministic evidence only |
| Audit truth | Audit checked only environment flags instead of the compile lock and runtime status | Critical | Compile constant and `BybitExecutionClient.status()` are verified |
| Database readiness | PostgreSQL was not verified by post-deploy logic | Critical | Canonical `ProjectDatabase.health()` is required for every backend |
| Deployment race | A shared `/tmp/phase11-health.json` could collide across runs | High | Unique same-directory temporary files and atomic replacement added |
| Deployment provenance | Release scripts did not require an approved immutable SHA and clean worktree | Critical | Expected SHA and clean-tree checks added |
| Dashboard load | Full filesystem audit could run every five seconds | High | Server-side locked TTL cache added |
| Dashboard reliability | Requests had no timeout, cancellation or backoff | Medium | AbortController, timeout, visibility awareness and exponential backoff added |
| Dashboard injection | Phase 10/11 panels rendered API values with `innerHTML` | High | DOM nodes, `textContent` and `replaceChildren` used exclusively |
| Dashboard accessibility | Theme, focus, mobile and reduced-motion behavior were incomplete | Medium | Responsive grids, system theme, persistent theme, focus-visible and reduced motion added |
| CI coverage | Phase 10/11 crash tests were not a separate mandatory check | Critical | Dedicated `Phase 11 Hardening` workflow added |
| Monitoring continuity | Monthly reports depended on manual CLI execution | High | Persistent systemd timer and hardened service added |

## Crash-test matrix

| Failure | Expected behavior |
| --- | --- |
| Process restart after authority activation | Authority reloads from canonical database and remains valid only while hash, lock and TTL match |
| Two simultaneous scaling activations | Exactly one wins the global optimistic lock; the other fails closed |
| Authority record modified in storage | Integrity check fails; no notional is authorized |
| Global lock removed or changed | Authority validation fails with `global_lock_matches` |
| Authority expires | It disappears from active API results and validation blocks it |
| Authority revoked | Validation blocks it and global lock is revoked |
| `NaN`/`Infinity` plan or API values | Rejected before authorization or sizing |
| Missing correlation for an open position | Sizing returns zero and `missing_correlation_data` |
| Correlation outside `[-1,1]` | Sizing returns zero and `invalid_correlation_data` |
| Duplicate position rows | Exposure is aggregated by symbol |
| Corrupt performance snapshot | Monthly report generation fails closed |
| Same snapshot replayed | Exact replay is idempotent and does not duplicate totals |
| Conflicting duplicate snapshot ID | Monthly report generation fails closed |
| Database unavailable | Production audit and post-deploy verification return blocked |
| Malformed unauthenticated JSON | Early middleware returns auth failure before body parsing or handler execution |
| Audit implementation throws | API returns a secret-free blocked report, not a false-ready state |
| Dashboard request hangs | Client aborts after timeout and backs off |
| Browser goes offline or tab becomes hidden | Polling pauses; missing values are not fabricated |
| Concurrent post-deploy verification | Unique temporary health/evidence files avoid collisions |
| Drawdown exceeds policy | Monthly CLI exits `2`, systemd unit fails and alert evidence is retained |
| Month contains no fills | Report is retained, CLI exits warning code `3`, timer unit treats it as a handled warning |

## Required verification

```bash
python -m pip install -r requirements-dev.txt
python -m pip check
python -m pip_audit -r requirements.txt --progress-spinner off
python -m compileall -q .
python -m pytest \
  tests/test_phase10_controlled_scaling.py \
  tests/test_phase10_capital_engine.py \
  tests/test_phase11_production_audit.py \
  tests/test_phase11_dashboard_contract.py \
  tests/test_phase11_crash_resilience.py \
  -q --tb=short
python -m pytest -q --tb=short
```

## Deployment gate

Set the approved commit explicitly:

```bash
export SHARIPOVAI_EXPECTED_SHA="$(git rev-parse HEAD)"
sudo -E bash deploy/vps/phase11_release_preflight.sh
```

Deploy only that SHA, then run:

```bash
sudo -E bash deploy/vps/phase11_post_deploy_verify.sh
sudo bash deploy/vps/install_phase10_monthly_monitor.sh
```

Required post-deploy evidence:

- audit status `ready_for_bounded_testnet_preflight`;
- no blockers;
- deployed SHA equals approved SHA;
- canonical database health is `ok`;
- HTTP health is a valid JSON object;
- Mainnet false;
- automatic campaign launch false;
- immutable audit SHA-256 present;
- dashboard APIs require an active administrator.

## First bounded Testnet campaign

Production readiness and Testnet campaign readiness are separate states. After production preflight passes:

1. provision isolated Bybit Testnet credentials without withdrawal or transfer permission;
2. prove authenticated private `order` and `execution` streams;
3. prove fresh persisted heartbeats and restart-safe reconciliation;
4. keep Mainnet absent and compiled out;
5. start only a finite, manually confirmed campaign window;
6. stay within the currently approved campaign notional; initial campaign policy remains 10–25 USDT;
7. collect at least 20 authenticated matched fills, actual fees and zero identity failures;
8. close the campaign window and revoke any scaling authority immediately;
9. generate Phase 8, Phase 9 and Phase 10 immutable evidence;
10. perform a separate manual report-bound decision.

## Residual risks

- Exchange outages, API changes and Testnet/Mainnet behavioral differences cannot be eliminated by local tests.
- Backtests remain model evidence and cannot prove future profitability.
- The production database, reverse proxy, host firewall, backups and secret store require deployment-specific validation.
- A campaign cannot be declared successful before authenticated private fills and actual fee evidence are collected.
- Scaling beyond 50 USDT or any Mainnet build requires a separate audited release and owner approval.
