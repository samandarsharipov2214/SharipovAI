from __future__ import annotations

import time

import news_monitor.agent_network as network


def _state() -> dict[str, object]:
    now = int(time.time())
    return {
        "last_refresh_at": now,
        "sources": {
            "sources": [
                {"id": "crypto_source", "name": "Crypto", "category": "crypto_news", "requires_credentials": False},
                {"id": "sport_source", "name": "Sport", "category": "sports", "requires_credentials": False},
                {"id": "x_source", "name": "X", "category": "x_news", "requires_credentials": True},
            ]
        },
        "news": {
            "items": [
                {
                    "source_id": "crypto_source",
                    "title": "Bitcoin exchange security alert",
                    "url": "https://example.test/crypto",
                    "credibility_percent": 88,
                    "urgency": "high",
                    "impact": "bearish",
                    "impact_score": -70,
                    "needs_confirmation": True,
                },
                {
                    "source_id": "sport_source",
                    "title": "League result",
                    "url": "https://example.test/sport",
                    "credibility_percent": 80,
                    "urgency": "low",
                    "impact": "neutral",
                    "impact_score": 0,
                    "needs_confirmation": False,
                },
            ]
        },
        "last_refresh_errors": [],
    }


def test_run_due_agents_builds_independent_memory_and_events(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(network, "STATE_PATH", tmp_path / "network.json")
    monkeypatch.setattr(network, "load_news_state", _state)

    result = network.run_due_agents(force=True)

    assert result["status"] == "ok"
    assert result["ran"] == len(network.AGENTS)
    status = network.network_status()
    by_id = {item["id"]: item for item in status["agents"]}
    assert by_id["crypto_ai"]["status"] == "active"
    assert by_id["crypto_ai"]["memory_count"] >= 1
    assert by_id["crypto_ai"]["events_emitted"] >= 1
    assert "risk_engine" in by_id["crypto_ai"]["routes_to"]
    assert by_id["sports_ai"]["status"] == "active"
    assert by_id["x_news_ai"]["status"] == "waiting_credentials"


def test_agent_detail_returns_persistent_memory(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(network, "STATE_PATH", tmp_path / "network.json")
    monkeypatch.setattr(network, "load_news_state", _state)
    network.run_agent("crypto_ai")

    detail = network.agent_detail("crypto_ai")

    assert detail["status"] == "ok"
    assert detail["agent"]["id"] == "crypto_ai"
    assert detail["memory"]
    assert detail["events"]


def test_unknown_agent_is_not_found(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(network, "STATE_PATH", tmp_path / "network.json")
    assert network.run_agent("missing_ai")["status"] == "not_found"
