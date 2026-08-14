from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTER = ROOT / "scripts" / "deploy_web2_refresh_fix.sh"
RUNTIME = ROOT / "scripts" / "deploy_market_paper_runtime.sh"
VERIFY = ROOT / "scripts" / "verify_web2_refresh_contracts.sh"
COMPOSE = ROOT / "deploy" / "vps" / "docker-compose.yml"
INDEX = ROOT / "dashboard" / "static" / "web2" / "index.html"


def test_web2_refresh_delegates_full_verification_to_transaction() -> None:
    source = OUTER.read_text(encoding="utf-8")

    assert "SHARIPOVAI_DEPLOY_PROFILE=web2-refresh" in source
    assert "deploy_market_paper_runtime.sh" in source
    assert "navigation_coordinator_v23.js" not in source
    assert "docker exec" not in source


def test_profile_verifier_runs_before_rollback_snapshot_is_committed() -> None:
    source = RUNTIME.read_text(encoding="utf-8")

    replaced = source.index("production_replaced=1")
    transaction_marker = source.index(
        'echo "[transaction] Verifying Dashboard/public/Telegram contracts before commit..."',
        replaced,
    )
    verifier = source.index(
        'bash "$ROOT/scripts/verify_web2_refresh_contracts.sh"',
        transaction_marker,
    )
    remove_backup = source.index('docker rm "$backup_container"', verifier)
    committed = source.index("production_replaced=0", remove_backup)

    assert replaced < transaction_marker < verifier < remove_backup < committed
    assert 'trap on_error ERR' in source
    assert source.index('trap on_error ERR') < replaced
    assert source.index('trap - ERR', verifier) > committed


def test_web2_verifier_is_version_agnostic_and_stdin_safe() -> None:
    source = VERIFY.read_text(encoding="utf-8")

    assert "navigation_coordinator_v23.js" not in source
    for family in (
        "navigation_coordinator_v",
        "runtime_render_guard_v",
        "tradingview_market_v",
        "market_intelligence_v",
        "campaign_operations_v",
        "campaign_decision_v",
        "campaign_monitor_v",
    ):
        assert family in source

    # Every Python heredoc executed inside the container must keep stdin open.
    assert source.count("docker exec -i") >= 3
    assert "WEB2_REFRESH_CONTRACTS_OK" in source


def test_current_web2_index_satisfies_version_agnostic_asset_families() -> None:
    index = INDEX.read_text(encoding="utf-8")

    assert "navigation_coordinator_v23.js" not in index
    for family in (
        "navigation_coordinator_v",
        "runtime_render_guard_v",
        "tradingview_market_v",
        "market_intelligence_v",
        "campaign_operations_v",
        "campaign_decision_v",
        "campaign_monitor_v",
    ):
        assert family in index


def test_candidate_and_runtime_have_a_canonical_git_path() -> None:
    runtime = RUNTIME.read_text(encoding="utf-8")
    compose = COMPOSE.read_text(encoding="utf-8")

    assert "command -v git >/dev/null" in runtime
    assert "git --version" in runtime
    assert runtime.index("command -v git >/dev/null") < runtime.index("production_replaced=1")
    assert 'PATH: "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"' in compose
