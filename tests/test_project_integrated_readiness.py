from __future__ import annotations

import importlib
import os
from pathlib import Path

from fastapi.testclient import TestClient


def test_all_runtime_components_share_one_database_and_required_routes(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'integrated.db'}")
    monkeypatch.setenv("SHARIPOVAI_DATABASE_REQUIRED", "1")
    monkeypatch.setenv("SHARIPOVAI_DISABLE_AUTH", "1")
    monkeypatch.setenv("AUTH_SECRET", "integration-secret")
    monkeypatch.setenv("ADMIN_USERNAME", "admin")
    monkeypatch.setenv("ADMIN_PASSWORD", "integration-password")
    monkeypatch.setenv("MARKET_STREAM_ENABLED", "0")
    monkeypatch.setenv("AUTONOMOUS_PAPER_ENABLED", "0")
    monkeypatch.setenv("AUTONOMOUS_TESTNET_BRIDGE_ENABLED", "0")
    monkeypatch.setenv("AUTONOMOUS_TESTNET_ENABLED", "0")
    monkeypatch.setenv("TESTNET_EXECUTION_ENABLED", "0")
    monkeypatch.setenv("EXCHANGE_LIVE_TRADING_ENABLED", "0")
    monkeypatch.setenv("EXECUTION_KILL_SWITCH", "1")
    monkeypatch.setenv("FEATURE_BYBIT_PRIVATE_ORDER_WS", "0")
    monkeypatch.setenv("BYBIT_ALLOW_LEGACY_EXCHANGE_CREDENTIALS", "0")
    monkeypatch.setenv("EXCHANGE_MODE", "sandbox")
    monkeypatch.setenv("AUTONOMOUS_TRADING_STAGE", "2")
    monkeypatch.setenv("AUTONOMOUS_PAPER_STATE_FILE", str(tmp_path / "paper.json"))
    monkeypatch.setenv("TESTNET_BRIDGE_STATE_FILE", str(tmp_path / "bridge.json"))
    monkeypatch.setenv("EXECUTION_JOURNAL_FILE", str(tmp_path / "journal.json"))

    import dashboard

    dashboard = importlib.reload(dashboard)
    app = dashboard.app
    database = app.state.project_database
    assert database.health()["status"] == "ok"
    assert app.state.news_agent_network.database is database
    assert app.state.news_agent_network.hub.database is database
    assert app.state.autonomous_paper_loop.database is database
    assert app.state.autonomous_testnet_bridge.database is database
    assert app.state.market_stream.worker is app.state.bybit_websocket_worker
    assert app.state.ai_organ_runtime_monitor.database is database

    paths = {route.path for route in app.routes}
    required = {
        "/health",
        "/api/system/database/status",
        "/api/project-memory/messages",
        "/api/market/bybit-websocket/status",
        "/api/news/agents/status",
        "/api/autonomous-paper/status",
        "/api/autonomous-testnet/status",
        "/api/exchange/private-order-ws/status",
        "/api/system/ai-organs",
    }
    assert required <= paths

    with TestClient(app) as client:
        health = client.get("/health")
        assert health.status_code == 200
        assert health.json()["database"]["status"] == "ok"


def test_public_market_activation_is_safe_and_explicit_off_wins(monkeypatch) -> None:
    from config.feature_flags import feature_enabled
    from dashboard.market_data_api import _configure_public_stream_feature

    monkeypatch.delenv("FEATURE_BYBIT_WEBSOCKET", raising=False)
    monkeypatch.setenv("MARKET_STREAM_ENABLED", "1")
    _configure_public_stream_feature()
    assert feature_enabled("FEATURE_BYBIT_WEBSOCKET") is True

    monkeypatch.setenv("FEATURE_BYBIT_WEBSOCKET", "0")
    _configure_public_stream_feature()
    assert feature_enabled("FEATURE_BYBIT_WEBSOCKET") is False


def test_financial_execution_and_private_stream_remain_locked(monkeypatch) -> None:
    monkeypatch.setenv("EXCHANGE_MODE", "sandbox")
    monkeypatch.setenv("EXCHANGE_BASE_URL", "https://api-testnet.bybit.com")
    monkeypatch.setenv("TESTNET_EXECUTION_ENABLED", "0")
    monkeypatch.setenv("AUTONOMOUS_TESTNET_ENABLED", "0")
    monkeypatch.setenv("AUTONOMOUS_TESTNET_BRIDGE_ENABLED", "0")
    monkeypatch.setenv("EXCHANGE_LIVE_TRADING_ENABLED", "0")
    monkeypatch.setenv("EXECUTION_KILL_SWITCH", "1")
    monkeypatch.setenv("FEATURE_BYBIT_PRIVATE_ORDER_WS", "0")
    monkeypatch.setenv("BYBIT_ALLOW_LEGACY_EXCHANGE_CREDENTIALS", "0")

    from exchange_connector.bybit_execution import BybitExecutionClient
    from exchange_connector.bybit_private_order_ws import BybitPrivateOrderWebSocket

    status = BybitExecutionClient().status()
    assert status["kill_switch"] is True
    assert status["testnet_execution_enabled"] is False
    assert status["live_execution_enabled"] is False
    assert BybitPrivateOrderWebSocket().enabled() is False
    forbidden = {"create_order", "place_order", "place_market_order", "amend_order", "cancel_order"}
    assert forbidden.isdisjoint(dir(BybitPrivateOrderWebSocket))


def test_render_blueprint_keeps_all_financial_locks() -> None:
    text = Path("render.yaml").read_text(encoding="utf-8")
    for name in (
        "AUTONOMOUS_TESTNET_BRIDGE_ENABLED",
        "AUTONOMOUS_TESTNET_ENABLED",
        "TESTNET_EXECUTION_ENABLED",
        "EXCHANGE_LIVE_TRADING_ENABLED",
        "FEATURE_BYBIT_PRIVATE_ORDER_WS",
        "BYBIT_ALLOW_LEGACY_EXCHANGE_CREDENTIALS",
    ):
        marker = f'- key: {name}\n        value: "0"'
        assert marker in text
    assert '- key: EXECUTION_KILL_SWITCH\n        value: "1"' in text
    assert '- key: EXCHANGE_MODE\n        value: sandbox' in text
    assert '- key: AUTONOMOUS_TRADING_STAGE\n        value: "2"' in text
