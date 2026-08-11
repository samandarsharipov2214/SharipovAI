# Audit hardening plan — 2026-08-11

This branch applies the approved hardening recommendations in bounded, reviewable blocks.

## Scope

1. Prevent accidental secondary exchange-order paths with a fail-closed AST/static guard.
2. Add bounded, dry-run-first retention tooling for high-volume operational events without touching immutable decision, execution, risk, portfolio, settlement or learning evidence.
3. Add an isolated backup restore drill for SQLite snapshots and document restore evidence requirements.
4. Add a canonical/compatibility/legacy runtime ownership map to reduce duplicated execution/decision paths.
5. Add a history secret scanner that reports only file/commit metadata, never secret values.
6. Add regression tests for the new guards and maintenance tools.

## Safety constraints

- Mainnet and Testnet remain disabled.
- `EXECUTION_KILL_SWITCH=1` remains required.
- No Docker socket mounting is introduced.
- No secrets, `.env.vps`, credentials, `CONSTITUTION.md`, Dockerfile, requirements.txt, `.github/`, `deploy/` or `execution/` files are changed in this block.
- Retention is deny-by-default for protected evidence namespaces and dry-run unless an explicit apply confirmation is supplied.
- No existing historical production rows are deleted by tests or CI.

## Follow-up blocks

After CI is green, continue with targeted write-amplification fixes in the concrete writers (`news_fetch_observations`, repeated council snapshots), then raise coverage on low-covered safety/observability modules and add periodic restore/secret-scan execution through the already-approved deployment/CI control path.
