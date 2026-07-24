from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMPOSE_PATH = ROOT / "deploy" / "vps" / "docker-compose.yml"
DOCKERFILE_PATH = ROOT / "Dockerfile"


def _compose_source() -> str:
    return COMPOSE_PATH.read_text(encoding="utf-8")


def test_data_permission_recovery_is_narrow_and_precedes_app_start() -> None:
    source = _compose_source()

    recovery_start = source.index("  data-permissions:\n")
    app_start = source.index("  sharipovai:\n")
    caddy_start = source.index("  caddy:\n")
    recovery = source[recovery_start:app_start]
    app = source[app_start:caddy_start]

    assert recovery_start < app_start
    assert '    image: sharipovai:${SHARIPOVAI_RELEASE_TAG:-local}' in recovery
    assert '    user: "0:0"' in recovery
    assert '    restart: "no"' in recovery
    assert "    network_mode: none" in recovery
    assert "    read_only: true" in recovery
    assert "      - sharipovai_data:/var/lib/sharipovai" in recovery
    assert "      - no-new-privileges:true" in recovery
    assert "    cap_drop:\n      - ALL" in recovery
    for capability in ("CHOWN", "DAC_OVERRIDE", "FOWNER"):
        assert f"      - {capability}" in recovery
    assert "chown -R 10001:10001 /var/lib/sharipovai" in recovery
    assert "chmod -R u+rwX,go-rwx /var/lib/sharipovai" in recovery
    assert "    depends_on:\n      data-permissions:\n        condition: service_completed_successfully" in app


def test_main_application_remains_unprivileged_and_execution_locked() -> None:
    source = _compose_source()
    app_start = source.index("  sharipovai:\n")
    caddy_start = source.index("  caddy:\n")
    app = source[app_start:caddy_start]

    assert "USER sharipovai" in DOCKERFILE_PATH.read_text(encoding="utf-8")
    assert "    cap_drop:\n      - ALL" in app
    assert "      - no-new-privileges:true" in app
    assert "      EXCHANGE_MODE: sandbox" in app
    for disabled in (
        "EXCHANGE_LIVE_TRADING_ENABLED",
        "FEATURE_BYBIT_LIVE_EXECUTION",
        "TESTNET_EXECUTION_ENABLED",
        "AUTONOMOUS_TESTNET_ENABLED",
        "AUTONOMOUS_TESTNET_BRIDGE_ENABLED",
        "FEATURE_BYBIT_PRIVATE_ORDER_WS",
        "RUNTIME_FILL_HARVESTER_ENABLED",
        "SCHEDULED_CAMPAIGN_ORCHESTRATOR_ENABLED",
    ):
        assert f'      {disabled}: "0"' in app
    assert '      EXECUTION_KILL_SWITCH: "1"' in app
