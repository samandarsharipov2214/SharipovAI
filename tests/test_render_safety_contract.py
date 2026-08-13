"""Source-controlled Render defaults must remain production-safe."""
from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RENDER = ROOT / "render.yaml"


def _value_for(key: str) -> str:
    text = RENDER.read_text(encoding="utf-8")
    match = re.search(
        rf"(?m)^\s*- key: {re.escape(key)}\s*$\n\s*value:\s*\"?([^\"\n]+)\"?\s*$",
        text,
    )
    assert match is not None, f"render.yaml missing {key}"
    return match.group(1).strip()


def test_render_keeps_legacy_virtual_account_autorun_disabled() -> None:
    assert _value_for("VIRTUAL_ACCOUNT_AUTORUN_ENABLED") == "0"


def test_render_keeps_execution_fail_closed() -> None:
    assert _value_for("EXECUTION_KILL_SWITCH") == "1"
    assert _value_for("TESTNET_EXECUTION_ENABLED") == "0"
    assert _value_for("AUTONOMOUS_TESTNET_ENABLED") == "0"
    assert _value_for("AUTONOMOUS_TESTNET_BRIDGE_ENABLED") == "0"
    assert _value_for("EXCHANGE_LIVE_TRADING_ENABLED") == "0"


def test_render_cannot_reconfigure_canonical_telegram_webhook() -> None:
    """Legacy Render must never race the canonical VPS for Telegram webhook ownership."""
    assert _value_for("TELEGRAM_AUTO_SET_WEBHOOK") == "0"
    assert _value_for("TELEGRAM_POLLING_ENABLED") == "0"


def test_render_blueprint_cannot_autodeploy_competing_production() -> None:
    text = RENDER.read_text(encoding="utf-8")

    assert "autoDeployTrigger: off" in text
    assert "autoDeployTrigger: checksPass" not in text
    assert "autoDeployTrigger: commit" not in text
    assert "autoDeploy: true" not in text
