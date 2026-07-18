from __future__ import annotations

from pathlib import Path

from scripts.phase11_first_campaign_checklist import evaluate_readiness

ROOT = Path(__file__).resolve().parents[1]


def _runtime_environment():
    return {
        "EXCHANGE_MODE": "sandbox",
        "EXCHANGE_BASE_URL": "https://api-testnet.bybit.com",
        "EXCHANGE_LIVE_TRADING_ENABLED": "0",
        "FEATURE_BYBIT_LIVE_EXECUTION": "0",
        "BYBIT_ALLOW_LEGACY_EXCHANGE_CREDENTIALS": "0",
        "EXECUTION_KILL_SWITCH": "0",
        "TESTNET_EXECUTION_ENABLED": "1",
        "AUTONOMOUS_TESTNET_ENABLED": "1",
        "AUTONOMOUS_TESTNET_BRIDGE_ENABLED": "1",
        "FEATURE_BYBIT_PRIVATE_ORDER_WS": "1",
        "RUNTIME_FILL_HARVESTER_ENABLED": "1",
        "SCHEDULED_CAMPAIGN_ORCHESTRATOR_ENABLED": "1",
        "PHASE6_TESTNET_RELEASE_GATE": "green",
        "EXECUTION_MAX_NOTIONAL_USDT": "25",
        "SHADOW_TESTNET_MAX_NOTIONAL_USDT": "25",
        "BYBIT_TESTNET_API_KEY": "configured-testnet-key",
        "BYBIT_TESTNET_API_SECRET": "configured-testnet-secret",
        "BYBIT_MAINNET_API_KEY": "",
        "BYBIT_MAINNET_API_SECRET": "",
    }


def _audit(sha):
    return {
        "status": "ready_for_bounded_testnet_preflight",
        "blockers": [],
        "deployed_sha": sha,
        "audit_sha256": "a" * 64,
        "mainnet_enabled": False,
        "automatic_campaign_launch": False,
    }


def _plan():
    return {"status": "ready", "can_start": True, "blockers": []}


def test_first_campaign_checklist_requires_every_bounded_runtime_gate():
    sha = "a" * 40
    report = evaluate_readiness(
        environ=_runtime_environment(),
        audit=_audit(sha),
        current_sha=sha,
        expected_sha=sha,
        plan=_plan(),
        active_scaling_authorities=0,
    )
    assert report["ready"] is True
    assert report["failed_checks"] == []
    assert report["maximum_order_notional_usdt"] == 25
    assert report["minimum_matched_fills"] == 20
    assert report["campaign_started"] is False
    assert report["runtime_flags_changed"] is False
    assert report["mainnet_enabled"] is False


def test_first_campaign_checklist_fails_closed_on_mainnet_or_sha_mismatch():
    expected = "a" * 40
    environ = _runtime_environment()
    environ["BYBIT_MAINNET_API_KEY"] = "must-never-be-present"
    report = evaluate_readiness(
        environ=environ,
        audit=_audit(expected),
        current_sha="b" * 40,
        expected_sha=expected,
        plan=_plan(),
        active_scaling_authorities=1,
    )
    assert report["ready"] is False
    assert "deployed_sha_matches" in report["failed_checks"]
    assert "mainnet_credentials_absent" in report["failed_checks"]
    assert "no_scaling_authority_before_first_campaign" in report["failed_checks"]


def test_first_campaign_checklist_rejects_unbounded_or_incomplete_runtime():
    sha = "c" * 40
    environ = _runtime_environment()
    environ["EXECUTION_MAX_NOTIONAL_USDT"] = "25.01"
    environ["BYBIT_TESTNET_API_SECRET"] = ""
    environ["EXECUTION_KILL_SWITCH"] = "1"
    report = evaluate_readiness(
        environ=environ,
        audit=_audit(sha),
        current_sha=sha,
        expected_sha=sha,
        plan={
            "status": "blocked",
            "can_start": False,
            "blockers": ["private_stream_stale"],
        },
        active_scaling_authorities=0,
    )
    assert report["ready"] is False
    assert "execution_notional_bounded" in report["failed_checks"]
    assert "isolated_testnet_credentials_complete" in report["failed_checks"]
    assert "finite_window_kill_switch_state" in report["failed_checks"]
    assert "canonical_plan_ready" in report["failed_checks"]


def test_exact_sha_rollback_is_locked_backed_up_and_self_restoring():
    script = (ROOT / "deploy/vps/phase11_rollback.sh").read_text(encoding="utf-8")
    required = (
        "I_APPROVE_PHASE11_EXACT_SHA_ROLLBACK",
        "SHARIPOVAI_ROLLBACK_SHA",
        "SHARIPOVAI_EXPECTED_SHA",
        "git merge-base --is-ancestor",
        "flock -n",
        "export_backup.sh",
        "creating verified backup with the current trusted exporter",
        "validate_financial_locks",
        "EXCHANGE_LIVE_TRADING_ENABLED",
        "EXECUTION_KILL_SWITCH",
        "TESTNET_EXECUTION_ENABLED",
        "restore_original",
        "docker compose build",
        "smoke_check.sh production",
        "/api/health",
    )
    assert all(token in script for token in required)
    assert "git reset --hard \"$TARGET_SHA\"" in script
    assert "git show \"$TARGET_SHA:deploy/vps/export_backup.sh\"" not in script
    assert "bash \"$ROOT/deploy/vps/export_backup.sh\"" in script


def test_phase11_deployment_paths_share_the_canonical_checkout():
    preflight = (ROOT / "deploy/vps/phase11_release_preflight.sh").read_text(
        encoding="utf-8"
    )
    verifier = (ROOT / "deploy/vps/phase11_post_deploy_verify.sh").read_text(
        encoding="utf-8"
    )
    installer = (ROOT / "deploy/vps/install_phase10_monthly_monitor.sh").read_text(
        encoding="utf-8"
    )
    service = (
        ROOT / "deploy/vps/systemd/sharipovai-monthly-performance.service"
    ).read_text(encoding="utf-8")
    for source in (preflight, verifier, installer):
        assert "/opt/sharipovai-repo" in source
        assert "APP_DIR" in source
    assert "rendered_service=\"$(mktemp)\"" in installer
    assert "chmod 0600 \"$rendered_service\"" in installer
    assert "/dev/stdin" not in installer
    assert "@SHARIPOVAI_ROOT@" in service
    assert "ReadWritePaths=-@SHARIPOVAI_ROOT@/data" in service
