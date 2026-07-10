from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

import dashboard.news_agent_network_api as api


def test_news_agent_network_endpoints(monkeypatch) -> None:
    monkeypatch.setattr(api, "refresh_news_if_stale", lambda **_: {"status": "fresh"})
    monkeypatch.setattr(
        api,
        "network_status",
        lambda run_due=False: {
            "status": "ok",
            "agents": [
                {
                    "id": "crypto_ai",
                    "name": "Crypto News AI",
                    "status": "active",
                    "mission": "Crypto",
                    "health_score": 95,
                    "source_count": 4,
                    "item_count": 8,
                    "memory_count": 20,
                    "data_freshness_seconds": 12,
                    "events_emitted": 2,
                    "last_action": "analyzed",
                    "routes_to": ["risk_engine"],
                }
            ],
            "coordinator": {"status": "active"},
        },
    )
    monkeypatch.setattr(api, "bridge_status", lambda: {"status": "ok", "thread_alive": True, "last_sent_count": 2})
    monkeypatch.setattr(api, "start_agent_network", lambda: {"status": "started"})
    monkeypatch.setattr(api, "start_agent_bridge", lambda: {"status": "started"})
    monkeypatch.setattr(api, "agent_detail", lambda agent_id, run_now=False: {"status": "ok", "agent": {"id": agent_id}})
    monkeypatch.setattr(api, "run_agent", lambda agent_id: {"status": "ok", "agent": {"id": agent_id}})
    monkeypatch.setattr(api, "run_due_agents", lambda force=False: {"status": "ok", "ran": 1})
    monkeypatch.setattr(api, "bridge_events", lambda: {"status": "ok", "sent": 1})

    app = FastAPI()
    api.install_news_agent_network_api(app)
    client = TestClient(app)

    status = client.get("/api/news-agents/status")
    assert status.status_code == 200
    assert status.json()["agents"][0]["id"] == "crypto_ai"
    assert status.json()["bridge"]["thread_alive"] is True

    detail = client.get("/api/news-agents/crypto_ai")
    assert detail.status_code == 200
    assert detail.json()["agent"]["id"] == "crypto_ai"

    run = client.post("/api/news-agents/crypto_ai/run")
    assert run.status_code == 200
    assert run.json()["bridge"]["sent"] == 1

    page = client.get("/news-agents")
    assert page.status_code == 200
    assert "Specialized News AI Network" in page.text
    assert "Crypto News AI" in page.text
