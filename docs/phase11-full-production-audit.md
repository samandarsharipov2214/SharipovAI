# Phase 11 — Full Production, Excellent Dashboard & Complete Audit

Phase 11 is the final fail-closed readiness layer. It does not claim Mainnet readiness, profit or a completed real campaign.

## Audit findings addressed

- production state was fragmented across stacked branches rather than `main`;
- no single deterministic production-readiness report existed;
- dashboard lacked one consolidated readiness surface and theme persistence;
- mobile layouts needed a final narrow-screen contract;
- deployment verification lacked a Phase 11 atomic evidence file;
- release preflight needed explicit Mainnet, kill-switch and 50 USDT ceiling checks.

## New controls

- `audit/phase11_production_audit.py` emits a SHA-256-addressed, secret-free report;
- `/api/production/phase11/audit` and `/api/production/phase11/overview` are admin-only;
- dashboard refreshes every five seconds only while visible;
- dark/light preference is persisted locally;
- `phase11_release_preflight.sh` blocks unsafe production state;
- `phase11_post_deploy_verify.sh` checks compile, HTTP health and SQLite integrity and writes atomically.

## Bounded Testnet campaign readiness

A real campaign may start only after all of the following are true:

1. the complete stacked branch chain has been merged and CI is green;
2. VPS deployment target SHA equals the approved commit;
3. preflight status is `ready_for_bounded_testnet_preflight`;
4. isolated Testnet credentials have no withdrawal or transfer permission;
5. private order and execution streams are authenticated and fresh;
6. kill switch remains engaged until the finite campaign window is explicitly opened;
7. notional is within the active authority and never above 50 USDT;
8. reconciliation, heartbeat, alert delivery and rollback are verified;
9. the campaign runner writes JSON and JSONL evidence;
10. completion is claimed only from authenticated private fills and actual fees.

## Commands

```bash
sudo -E bash deploy/vps/phase11_release_preflight.sh
sudo -E bash deploy/vps/phase11_post_deploy_verify.sh
python -m pytest tests/test_phase11_production_audit.py tests/test_phase11_dashboard_contract.py -q --tb=short
python -m pytest -q --tb=short
```

Exit code `2` always means blocked. A warning is never silently promoted to success.
