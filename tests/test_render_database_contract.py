from __future__ import annotations

from pathlib import Path


def test_render_blueprint_keeps_trading_locked_and_database_required() -> None:
    text = Path("render.yaml").read_text(encoding="utf-8")
    assert "name: sharipovai-db" in text
    assert "property: connectionString" in text
    assert "preDeployCommand: python scripts/migrate_project_db.py" in text
    assert "healthCheckPath: /health" in text
    assert "SHARIPOVAI_DATABASE_REQUIRED" in text
    assert 'TESTNET_EXECUTION_ENABLED\n        value: "0"' in text
    assert 'EXECUTION_KILL_SWITCH\n        value: "1"' in text
    assert 'EXCHANGE_LIVE_TRADING_ENABLED\n        value: "0"' in text
    assert "EXCHANGE_API_KEY" not in text
    assert "EXCHANGE_API_SECRET" not in text
    assert "BYBIT_MAINNET_API_KEY" in text
    assert "BYBIT_ALLOW_LEGACY_EXCHANGE_CREDENTIALS" in text
