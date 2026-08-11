# SharipovAI Runtime Ownership Map

This map is an operational safety artifact. It prevents legacy modules from quietly becoming a second source of truth.

| Area | Canonical owner | Compatibility-only surfaces | Retirement rule |
|---|---|---|---|
| Risk decisions | `risk_engine/` | `risk/` | Compatibility code may read/project canonical state but must not own execution risk decisions. |
| Learning | `learning_engine/` + canonical `ProjectDatabase` persistence | `learning/` | Compatibility code must not create a separate durable learning history. |
| Memory | `storage/project_database.py` and canonical memory adapters | `memory/`, `memory_engine/` | Legacy stores may be migration/read adapters only. |
| Paper execution | canonical autonomous/paper runtime and `trading_core` contracts | old demo/virtual-account adapters | No second tick loop, reset loop, catch-up executor or independent balance source. |
| Exchange execution | `exchange_connector/bybit_execution.py` with `ApprovedExecutionRequest` | legacy exchange wrappers | No raw order submission path outside the canonical execution client. |
| Decision quality | `decision_quality/` | older decision projection layers | Legacy views may display results but must not independently approve execution. |
| Dashboard/Telegram truth | canonical ProjectDatabase-backed services | legacy/demo endpoints | Compatibility endpoints must be read-only projections or tombstones. |

## CI invariant

`tests/test_audit_hardening.py` executes the static execution-path guard. Any newly introduced direct order primitive outside the canonical execution module fails the test suite.

## Removal process

A compatibility module can be deleted only after: imports are searched, dashboard/Telegram projections are confirmed canonical, migrations are complete, full pytest is green, and production rollback does not depend on the module. Dead code must not be kept merely because it once existed.
