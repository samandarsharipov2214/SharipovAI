from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
COMPOSE_PATH = ROOT / "deploy" / "vps" / "docker-compose.yml"
DOCKERFILE_PATH = ROOT / "Dockerfile"


def test_data_permission_recovery_is_narrow_and_precedes_app_start() -> None:
    payload = yaml.safe_load(COMPOSE_PATH.read_text(encoding="utf-8"))
    services = payload["services"]
    recovery = services["data-permissions"]
    app = services["sharipovai"]

    assert recovery["image"] == app["image"]
    assert recovery["user"] == "0:0"
    assert recovery["restart"] == "no"
    assert recovery["network_mode"] == "none"
    assert recovery["read_only"] is True
    assert recovery["volumes"] == ["sharipovai_data:/var/lib/sharipovai"]
    assert recovery["security_opt"] == ["no-new-privileges:true"]
    assert recovery["cap_drop"] == ["ALL"]
    assert set(recovery["cap_add"]) == {"CHOWN", "DAC_OVERRIDE", "FOWNER"}

    command = "\n".join(recovery["command"])
    assert "chown -R 10001:10001 /var/lib/sharipovai" in command
    assert "chmod -R u+rwX,go-rwx /var/lib/sharipovai" in command
    assert app["depends_on"]["data-permissions"]["condition"] == "service_completed_successfully"


def test_main_application_remains_unprivileged_and_execution_locked() -> None:
    payload = yaml.safe_load(COMPOSE_PATH.read_text(encoding="utf-8"))
    app = payload["services"]["sharipovai"]
    environment = app["environment"]

    assert "USER sharipovai" in DOCKERFILE_PATH.read_text(encoding="utf-8")
    assert app["cap_drop"] == ["ALL"]
    assert app["security_opt"] == ["no-new-privileges:true"]
    assert environment["EXCHANGE_MODE"] == "sandbox"
    assert str(environment["EXCHANGE_LIVE_TRADING_ENABLED"]) == "0"
    assert str(environment["FEATURE_BYBIT_LIVE_EXECUTION"]) == "0"
    assert str(environment["TESTNET_EXECUTION_ENABLED"]) == "0"
    assert str(environment["AUTONOMOUS_TESTNET_ENABLED"]) == "0"
    assert str(environment["AUTONOMOUS_TESTNET_BRIDGE_ENABLED"]) == "0"
    assert str(environment["FEATURE_BYBIT_PRIVATE_ORDER_WS"]) == "0"
    assert str(environment["RUNTIME_FILL_HARVESTER_ENABLED"]) == "0"
    assert str(environment["SCHEDULED_CAMPAIGN_ORCHESTRATOR_ENABLED"]) == "0"
    assert str(environment["EXECUTION_KILL_SWITCH"]) == "1"
