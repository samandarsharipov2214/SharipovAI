from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEPLOY = ROOT / "deploy" / "vps"
VALIDATOR = DEPLOY / "validate_runtime_env.py"


def _base_env() -> str:
    return "\n".join(
        [
            "DOMAIN=trade.example.net",
            "AUTH_SECRET=" + "a" * 48,
            "ADMIN_USERNAME=operator",
            "ADMIN_PASSWORD=" + "b" * 20,
            "EXCHANGE_MODE=sandbox",
            "EXCHANGE_BASE_URL=https://api-testnet.bybit.com",
            "EXCHANGE_LIVE_TRADING_ENABLED=0",
            "FEATURE_BYBIT_LIVE_EXECUTION=0",
            "EXECUTION_KILL_SWITCH=1",
            "TESTNET_EXECUTION_ENABLED=0",
            "AUTONOMOUS_TESTNET_ENABLED=0",
            "AUTONOMOUS_TESTNET_BRIDGE_ENABLED=0",
            "FEATURE_BYBIT_TESTNET=0",
            "FEATURE_BYBIT_PRIVATE_ORDER_WS=0",
            "RUNTIME_FILL_HARVESTER_ENABLED=0",
            "SCHEDULED_CAMPAIGN_ORCHESTRATOR_ENABLED=0",
            "PHASE6_TESTNET_RELEASE_GATE=blocked",
            "BYBIT_ALLOW_LEGACY_EXCHANGE_CREDENTIALS=0",
            "CRITICAL_ALERT_MONITOR_ENABLED=1",
            "ALERT_DELIVERY_ENABLED=0",
            "EXECUTION_MAX_NOTIONAL_USDT=25",
            "SHADOW_TESTNET_MAX_NOTIONAL_USDT=25",
        ]
    ) + "\n"


def _run_validator(*files: Path, mode: str) -> tuple[int, dict]:
    command = [sys.executable, str(VALIDATOR)]
    for path in files:
        command.extend(["--env-file", str(path)])
    command.extend(["--mode", mode, "--json"])
    result = subprocess.run(command, text=True, capture_output=True, check=False)
    return result.returncode, json.loads(result.stdout)


def test_runtime_env_uses_separate_production_and_campaign_files(tmp_path) -> None:
    base = tmp_path / ".env.vps"
    overlay = tmp_path / ".env.testnet-campaign"
    base.write_text(_base_env(), encoding="utf-8")
    overlay.write_text(
        "PHASE6_TESTNET_RELEASE_GATE=green\n"
        "BYBIT_TESTNET_API_KEY=testnet-key\n"
        "BYBIT_TESTNET_API_SECRET=testnet-secret\n",
        encoding="utf-8",
    )
    code, production = _run_validator(base, mode="production")
    assert code == 0 and production["safe_to_continue"] is True
    code, campaign = _run_validator(base, overlay, mode="testnet-campaign")
    assert code == 0 and campaign["safe_to_continue"] is True
    assert campaign["mainnet_enabled"] is False


def test_runtime_env_rejects_mainnet_credentials_and_caps_above_25(tmp_path) -> None:
    base = tmp_path / ".env.vps"
    overlay = tmp_path / ".env.testnet-campaign"
    base.write_text(_base_env() + "BYBIT_MAINNET_API_KEY=forbidden\n", encoding="utf-8")
    overlay.write_text(
        "PHASE6_TESTNET_RELEASE_GATE=green\n"
        "BYBIT_TESTNET_API_KEY=testnet-key\n"
        "BYBIT_TESTNET_API_SECRET=testnet-secret\n"
        "EXECUTION_MAX_NOTIONAL_USDT=26\n",
        encoding="utf-8",
    )
    code, report = _run_validator(base, overlay, mode="testnet-campaign")
    assert code == 2
    assert any("Mainnet execution credentials" in value for value in report["errors"])
    assert any("10..25" in value for value in report["errors"])


def test_phase7_campaign_transition_scripts_are_fail_closed() -> None:
    scripts = [DEPLOY / "smoke_check.sh", DEPLOY / "testnet_campaign_deploy.sh", DEPLOY / "testnet_campaign_stop.sh"]
    for script in scripts:
        subprocess.run(["bash", "-n", str(script)], check=True)
    deploy = (DEPLOY / "testnet_campaign_deploy.sh").read_text(encoding="utf-8")
    stop = (DEPLOY / "testnet_campaign_stop.sh").read_text(encoding="utf-8")
    assert "I_APPROVE_BOUNDED_TESTNET_RUNTIME_DEPLOYMENT" in deploy
    assert "I_APPROVE_RESTORE_PRODUCTION_KILL_SWITCH" in stop
    assert deploy.index("phase7_preflight.sh") < deploy.index("export_backup.sh")
    assert deploy.index("systemd-run") < deploy.index("up -d --force-recreate")
    assert "restoring production-safe compose" in deploy
    assert "TESTNET_CAMPAIGN_MAX_WINDOW_SECONDS" in deploy
    assert "sharipovai-testnet-auto-stop" in deploy
    assert "systemctl is-active" in deploy
    assert "sharipovai-testnet-auto-stop.timer" in stop
    assert 'flock -w "${LOCK_WAIT_SECONDS}"' in stop


def test_compose_and_image_keep_mainnet_off_and_drop_capabilities() -> None:
    base = (DEPLOY / "docker-compose.yml").read_text(encoding="utf-8")
    override = (DEPLOY / "docker-compose.testnet-campaign.yml").read_text(encoding="utf-8")
    production_env = (DEPLOY / ".env.vps.example").read_text(encoding="utf-8")
    campaign_env = (DEPLOY / ".env.testnet-campaign.example").read_text(encoding="utf-8")
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert 'EXECUTION_KILL_SWITCH: "1"' in base
    assert 'FEATURE_BYBIT_LIVE_EXECUTION: "0"' in base
    assert 'cap_drop:' in base and '- ALL' in base
    assert 'no-new-privileges:true' in base
    assert 'BYBIT_TESTNET_API_KEY=' not in production_env
    assert 'BYBIT_TESTNET_API_KEY=' in campaign_env
    assert '${BYBIT_TESTNET_API_KEY:?' in override
    assert 'EXECUTION_KILL_SWITCH: "0"' in override
    assert 'ai.sharipov.mainnet-enabled: "false"' in override
    assert "python -m pip check" in dockerfile
    assert "python -m compileall" in dockerfile
