from __future__ import annotations

from fastapi.testclient import TestClient

from dashboard.app import create_app


def _configure_runtime(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("SHARIPOVAI_DISABLE_AUTH", "1")
    monkeypatch.setenv("VIRTUAL_ACCOUNT_STATE_FILE", str(tmp_path / "virtual-account.json"))
    monkeypatch.setenv("NEWS_MONITOR_STATE_FILE", str(tmp_path / "news-state.json"))
    monkeypatch.setenv("NEWS_AGENT_NETWORK_STATE_FILE", str(tmp_path / "news-agents.json"))
    monkeypatch.setenv("NEWS_AGENT_BRIDGE_STATE_FILE", str(tmp_path / "news-bridge.json"))
    monkeypatch.setenv("BOT_COMMUNICATION_DB", str(tmp_path / "bot-network.sqlite3"))
    monkeypatch.setenv("VIRTUAL_ACCOUNT_BOOTSTRAP_TICKS", "1")
    monkeypatch.setenv("VIRTUAL_ACCOUNT_MAX_CATCH_UP_TICKS", "1")


def test_specialized_news_routes_are_installed(monkeypatch, tmp_path) -> None:
    _configure_runtime(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        response = client.get("/api/news-agents/status")
        assert response.status_code == 200
        payload = response.json()
        assert "agents" in payload
        assert payload.get("agent_count", len(payload.get("agents", []))) >= 1


def test_ai_bots_endpoint_returns_nine_canonical_organs(monkeypatch, tmp_path) -> None:
    _configure_runtime(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        response = client.get("/api/ai-bots")
        assert response.status_code == 200
        payload = response.json()
        bots = payload.get("bots", payload.get("agents", []))
        ids = {bot.get("id") for bot in bots}
        assert len(bots) == 9
        assert payload["summary"]["canonical_ai_count"] == 9
        assert "virtual_execution" in ids
        assert "decision_quality" in ids
        assert "telegram_bot_ai" not in ids
        assert "stress_lab_ai" not in ids


def test_legacy_demo_state_mirrors_virtual_account(monkeypatch, tmp_path) -> None:
    _configure_runtime(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        virtual_payload = client.get("/api/virtual-account/state").json()
        legacy_payload = client.get("/api/demo/state").json()

        virtual_state = virtual_payload["state"]
        legacy_state = legacy_payload["state"]
        virtual_summary = virtual_state.get("summary", {})

        assert legacy_payload["deprecated"] is True
        assert legacy_payload["use"] == "/api/virtual-account/state"
        assert legacy_state["mode"] == "VIRTUAL_ACCOUNT"
        assert legacy_state["equity"] == virtual_summary.get("equity", virtual_state.get("equity"))
        assert legacy_state["trades"] == virtual_state["trades"]
        assert legacy_state["online_monitoring"]["real_orders_blocked"] is True


def test_realtime_status_exposes_news_startup_truth(monkeypatch, tmp_path) -> None:
    _configure_runtime(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        response = client.get("/api/realtime/status")
        assert response.status_code == 200
        payload = response.json()
        assert payload["startup"]["news_agent_network_api_installed"] is True
        assert payload["agents"]["summary"]["total_bots"] == 9
        assert payload["virtual_account"]["real_orders_blocked"] is True
