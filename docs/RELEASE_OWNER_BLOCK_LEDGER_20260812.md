# Release-owner block ledger — 2026-08-12

This is an evidence ledger, not a substitute for executable tests.  A block is
only marked `DONE` when its stated evidence is available.

| Block | Status | Evidence / next action |
|---|---|---|
| A — final main baseline | DONE | `f549bfc66d82acee6d0b1b20dba1f736e1f94565`; post-merge Tests, Project Guardrails, Phase 11 Hardening, Dashboard Stabilization and Проверка SharipovAI all succeeded. Production Smoke is separately tracked as an external Render 503. |
| B — legacy ownership | ACTIVE | Launch-check was found reading `PaperActivityEngine`; it is moved to the canonical autonomous-paper projection in this change. Remaining compatibility surfaces require explicit classification. |
| C — DB write amplification | ACTIVE | Namespace writers and production-compatible growth evidence are being traced before any retention change. |
| D — DB growth measurement | ACTIVE | Read-only VPS measurement is required; no delete/VACUUM is permitted. |
| E — CPU/background loops | ACTIVE | Runtime loops are being enumerated with their write/network effects. |
| F — AI memory durability | ACTIVE | Canonical persistence and restart contracts are being checked. |
| G — cross-surface truth | ACTIVE | Dashboard launch diagnostics now use the canonical paper state; broader API/Telegram contracts remain. |
| H — execution security | ACTIVE | Existing AST guard is green; adversarial alias/dynamic cases are being reviewed. |
| I — secret/supply chain/history | ACTIVE | History scanner is present; scan and dependency evidence are pending. |
| J — backup/restore | ACTIVE | Restore drill is present; deployed timer and evidence are pending verification. |
| K — observability | ACTIVE | Existing metrics and gaps are being mapped before adding instrumentation. |
| L — deploy drift detection | ACTIVE | Source-controlled provenance contract is being located. |
| M — deploy watcher | ACTIVE | Repository source and installed watcher must be compared read-only. |
| N — critical-boundary tests | ACTIVE | Tests added only alongside demonstrated gaps. |
| O — external audit claims | ACTIVE | Claims will be classified from code and tests, not historic reports. |
| P — architectural integrity | ACTIVE | Canonical Market → Council → DQ → gates → paper → settlement → learning flow is being verified. |
| Q — repository cleanup | ACTIVE | Generated/tracked artifacts are deferred until ownership verification. |
| R — final matrix | ACTIVE | Targeted tests run per repair; full verification is reserved for the final change set. |
| S — PR/merge discipline | ACTIVE | Any new repair will be reviewed, tested, pushed and proposed separately. |
| T — VPS convergence | ACTIVE | Read-only checks may proceed; deployment requires existing approval policy. |

## External condition recorded

The three `Production Smoke` runs on merged `059d72e9` failed because
`https://sharipovai-bot.onrender.com` returned HTTP 503 and a non-JSON health
response.  The post-merge repository CI for `f549bfc6` is green.  This is not
treated as a repository CI pass or as a reason to weaken smoke checks.
