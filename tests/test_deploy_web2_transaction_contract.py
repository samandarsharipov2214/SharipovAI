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


def test_runtime_uses_the_exact_image_that_passed_candidate_verification() -> None:
    source = RUNTIME.read_text(encoding="utf-8")

    assert 'ACTIVE_IMAGE_REF="vps-sharipovai:latest"' not in source
    assert 'export SHARIPOVAI_RELEASE_TAG="deploy-${head_sha:0:12}-' in source
    assert 'candidate_image_ref="sharipovai:${SHARIPOVAI_RELEASE_TAG}"' in source
    assert 'docker compose build "$SERVICE"' in source
    assert 'docker image inspect "$candidate_image_ref"' in source
    assert 'image: ${candidate_image_ref}' in source

    build = source.index('docker compose build "$SERVICE"')
    runtime_image = source.index('image: ${candidate_image_ref}')
    replaced = source.index("production_replaced=1")
    assert build < runtime_image < replaced


def test_candidate_identity_is_proven_before_production_replacement() -> None:
    source = RUNTIME.read_text(encoding="utf-8")

    revision_check = source.index("Candidate image revision mismatch")
    web2_check = source.index("Candidate Web2 index does not match exact Git HEAD")
    identity_ok = source.index("CANDIDATE_IMAGE_IDENTITY_OK")
    replaced = source.index("production_replaced=1")

    assert revision_check < web2_check < identity_ok < replaced
    assert 'git -c safe.directory="$ROOT" -C "$ROOT" "$@"' in source
    assert 'git_repo show "${head_sha}:dashboard/static/web2/index.html"' in source
    assert 'docker run --rm --entrypoint sha256sum "$candidate_image_ref"' in source
    assert "git config --global" not in source


def test_running_container_image_id_must_match_verified_candidate() -> None:
    source = RUNTIME.read_text(encoding="utf-8")

    replaced = source.index("production_replaced=1")
    running_check = source.index("Production container is not running the verified candidate image.")
    market_verify = source.index('echo "[5/6] Verifying the running market-backed virtual account..."')

    assert replaced < running_check < market_verify
    assert "RUNNING_IMAGE_IDENTITY_OK" in source
    assert "docker inspect -f '{{.Image}}' \"$SERVICE\"" in source
