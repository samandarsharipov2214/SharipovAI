from __future__ import annotations

from fastapi.testclient import TestClient

from ai_architecture_registry import CANONICAL_AI_ORGANS
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


def test_ai_bots_endpoint_returns_canonical_organs(monkeypatch, tmp_path) -> None:
    _configure_runtime(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        response = client.get("/api/ai-bots")
        assert response.status_code == 200
        payload = response.json()
        bots = payload.get("bots", payload.get("agents", []))
        expected_names = {organ.name for organ in CANONICAL_AI_ORGANS}
        actual_names = {str(item.get("name", "")) for item in bots}
        assert actual_names == expected_names
        assert len(bots) == len(expected_names)
        assert payload["summary"]["canonical_ai_count"] == len(CANONICAL_AI_ORGANS)


def test_legacy_virtual_account_endpoint_is_disabled(monkeypatch, tmp_path) -> None:
    _configure_runtime(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        virtual = client.get("/api/virtual-account/state")
        assert virtual.status_code == 410
        payload = virtual.json()
        assert payload["status"] == "blocked"
        assert payload["source_of_truth"] == "CouncilAuthorizedPaperLoop"
        assert payload["automatic_legacy_mutation"] is False


def test_realtime_status_exposes_news_startup_truth(monkeypatch, tmp_path) -> None:
    _configure_runtime(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        response = client.get("/api/realtime/status")
        assert response.status_code == 200
        payload = response.json()
        assert payload["startup"]["news_agent_network_api_installed"] is True
        assert payload["agents"]["summary"]["total_bots"] == 9
        assert payload["virtual_account"]["real_orders_blocked"] is True
