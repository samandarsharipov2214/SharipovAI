# SharipovAI Safe Change Process

This process is mandatory for architecture, exchange, trading, risk, account, authentication, and persistence changes.

## Non-negotiable rules

1. Do not change `main` directly.
2. Reuse or extend an existing AI/module before creating another one.
3. New risky capabilities must be protected by a registered feature flag and default to disabled.
4. Live trading must remain disabled unless a dedicated audited change explicitly enables it.
5. Never commit credentials, tokens, private keys, account snapshots, or production data.
6. Every behavior change requires tests covering the new behavior and the previous safety behavior.
7. A pull request must contain one coherent change. Security fixes and feature work must not be mixed.

## Required workflow

1. Read current project documentation and recent relevant changes.
2. Identify existing modules, callers, APIs, state files, and tests affected by the change.
3. Record the expected behavior and failure behavior before editing.
4. Create an isolated branch from the current default branch.
5. Implement the smallest reversible change.
6. Add or update tests.
7. Run compilation and the full pytest suite.
8. Inspect the final diff for unrelated changes and secret exposure.
9. Open a draft pull request with impact, risks, rollback, and verification results.
10. Merge only after required checks pass.

## Bybit rollout order

The rollout order is fixed unless a security issue requires an earlier correction:

1. Read-only account and public market data.
2. Authentication, regional endpoint, time synchronization, rate limiting, and reconnect safety.
3. Non-executing order preview and exchange-instrument validation.
4. Testnet execution behind a disabled feature flag and kill switch.
5. Testnet reconciliation, duplicate-order prevention, failure recovery, and audit records.
6. Restricted live subaccount execution with explicit short-lived approval.

Skipping stages is not allowed.

## Required rollback design

Every new feature must be removable without deleting code by setting its feature flag to false. Trading-related rollbacks must also work through `EXECUTION_KILL_SWITCH=1` and `EXCHANGE_LIVE_TRADING_ENABLED=0`.

## Pull request evidence

Each pull request must report:

- files and modules changed;
- APIs or state affected;
- tests executed and their result;
- security and capital risks;
- feature flag and default state;
- rollback procedure;
- remaining limitations.
