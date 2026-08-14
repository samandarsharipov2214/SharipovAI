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
    assert "refusing to modify .env.vps" in source
    assert "path.write_text" not in source


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
    assert 'candidate_image_id="$(docker image inspect -f' in source
    assert 'docker image inspect "$candidate_image_ref"' in source
    assert 'image: ${candidate_image_ref}' in source

    build = source.index('docker compose build "$SERVICE"')
    immutable_id = source.index('candidate_image_id="$(docker image inspect -f', build)
    runtime_image = source.index('image: ${candidate_image_ref}')
    replaced = source.index("production_replaced=1")
    assert build < immutable_id < runtime_image < replaced


def test_candidate_identity_is_proven_before_production_replacement() -> None:
    source = RUNTIME.read_text(encoding="utf-8")

    revision_check = source.index("Candidate image revision mismatch")
    web2_check = source.index("Candidate Web2 index does not match exact Git HEAD")
    identity_ok = source.index("CANDIDATE_IMAGE_IDENTITY_OK")
    replaced = source.index("production_replaced=1")

    assert revision_check < web2_check < identity_ok < replaced
    assert 'git -c safe.directory="$ROOT" -C "$ROOT" "$@"' in source
    assert 'git_repo show "${head_sha}:dashboard/static/web2/index.html"' in source
    assert 'docker run --rm --entrypoint sha256sum "$candidate_image_id"' in source
    assert "git config --global" not in source


def test_candidate_checks_do_not_inherit_production_data_or_network() -> None:
    source = RUNTIME.read_text(encoding="utf-8")
    candidate_section = source[
        source.index("candidate_run_base=(") : source.index('runtime_override="$(mktemp', source.index("candidate_run_base=("))
    ]

    assert "docker compose run" not in candidate_section
    assert "docker run --rm" in candidate_section
    assert "--network none" in candidate_section
    assert "--tmpfs /var/lib/sharipovai:" in candidate_section
    assert "uid=10001,gid=10001,mode=0700" in candidate_section
    assert '--env-file "$DEPLOY/.env.vps"' in candidate_section
    assert '"${candidate_run_base[@]}"' in candidate_section
    assert '"$candidate_image_id"' in candidate_section
    assert "sharipovai_data" not in candidate_section
    assert "$data_volume" not in candidate_section

    # Candidate validation must remain execution-disabled even if .env.vps changes.
    for contract in (
        "EXECUTION_KILL_SWITCH=1",
        "EXCHANGE_LIVE_TRADING_ENABLED=0",
        "FEATURE_BYBIT_LIVE_EXECUTION=0",
        "TESTNET_EXECUTION_ENABLED=0",
        "AUTONOMOUS_TESTNET_ENABLED=0",
        "AUTONOMOUS_TESTNET_BRIDGE_ENABLED=0",
        "FEATURE_BYBIT_PRIVATE_ORDER_WS=0",
        "RUNTIME_FILL_HARVESTER_ENABLED=0",
        "SCHEDULED_CAMPAIGN_ORCHESTRATOR_ENABLED=0",
    ):
        assert contract in candidate_section


def test_candidate_health_wait_is_bounded_by_outer_probe_timeout() -> None:
    source = RUNTIME.read_text(encoding="utf-8")

    assert 'CANDIDATE_HEALTH_WAIT_SECONDS="${SHARIPOVAI_DEPLOY_CANDIDATE_HEALTH_WAIT_SECONDS:-120}"' in source
    assert "CANDIDATE_HEALTH_WAIT_SECONDS >= CANDIDATE_PROBE_TIMEOUT_SECONDS" in source
    assert "deadline=$(( $(date +%s) + CANDIDATE_HEALTH_WAIT_SECONDS ))" in source
    assert 'while [ "$(date +%s)" -lt "$deadline" ]' in source
    assert "for _ in $(seq 1 60)" not in source
    assert 'run_bounded "$CANDIDATE_PROBE_TIMEOUT_SECONDS" "${candidate_run_base[@]}"' in source


def test_deploy_refuses_low_disk_and_cleans_failed_candidate_tag() -> None:
    source = RUNTIME.read_text(encoding="utf-8")

    disk_check = source.index("DEPLOY_DISK_PREFLIGHT_FAILED")
    build = source.index('docker compose build "$SERVICE"')
    assert disk_check < build
    assert 'SHARIPOVAI_DEPLOY_MIN_FREE_DISK_GB:-20' in source
    assert "candidate_committed=0" in source
    assert 'docker image rm "$candidate_image_ref"' in source
    assert "candidate_committed=1" in source
    assert source.index("candidate_committed=1") > source.index('docker rm "$backup_container"')


def test_running_container_image_id_must_match_verified_candidate() -> None:
    source = RUNTIME.read_text(encoding="utf-8")

    replaced = source.index("production_replaced=1")
    running_check = source.index("Production container is not running the verified candidate image.")
    market_verify = source.index('echo "[5/6] Verifying the running market-backed virtual account..."')

    assert replaced < running_check < market_verify
    assert "RUNNING_IMAGE_IDENTITY_OK" in source
    assert "docker inspect -f '{{.Image}}' \"$SERVICE\"" in source
    # Do not re-resolve the mutable tag after candidate verification.
    assert source.count('candidate_image_id="$(docker image inspect -f') == 1


def test_deploy_commands_and_public_probes_are_bounded() -> None:
    source = RUNTIME.read_text(encoding="utf-8")
    verifier = VERIFY.read_text(encoding="utf-8")

    assert 'run_bounded "$BUILD_TIMEOUT_SECONDS" docker compose build "$SERVICE"' in source
    assert 'run_bounded "$CANDIDATE_TEST_TIMEOUT_SECONDS" "${candidate_run_base[@]}"' in source
    assert 'run_bounded "$CANDIDATE_PROBE_TIMEOUT_SECONDS" "${candidate_run_base[@]}"' in source
    assert 'run_bounded "$RUNTIME_UP_TIMEOUT_SECONDS" docker compose -p' in source
    assert 'run_bounded "$RUNTIME_VERIFY_TIMEOUT_SECONDS" docker exec' in source
    assert "--connect-timeout 5 --max-time 15" in source
    assert "--connect-timeout 5 --max-time 15" in verifier
