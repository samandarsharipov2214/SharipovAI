from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

import dashboard.news_agent_network_api as api


def test_news_agent_network_endpoints(monkeypatch) -> None:
    monkeypatch.setattr(api, "refresh_news_if_stale", lambda app=None, **_: {"status": "fresh"})
    monkeypatch.setattr(
        api,
        "network_status",
        lambda run_due=False, app=None: {
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
    monkeypatch.setattr(
        api,
        "bridge_status",
        lambda app=None: {
            "status": "ok",
            "delivery_mode": "shared_database",
            "consumer_active": True,
            "sent_count": None,
        },
    )
    monkeypatch.setattr(api, "start_agent_network", lambda app=None: {"status": "started"})
    monkeypatch.setattr(api, "start_agent_bridge", lambda app=None: {"status": "ready"})
    monkeypatch.setattr(
        api,
        "agent_detail",
        lambda agent_id, run_now=False, app=None: {"status": "ok", "agent": {"id": agent_id}},
    )
    monkeypatch.setattr(
        api,
        "run_agent",
        lambda agent_id, app=None: {
            "status": "ok",
            "agent": {"id": agent_id},
            "bridge": {
                "status": "ok",
                "delivery_mode": "shared_database",
                "consumer_active": True,
                "sent": None,
            },
        },
    )
    monkeypatch.setattr(
        api,
        "run_due_agents",
        lambda force=False, app=None: {"status": "ok", "ran": 1},
    )
    monkeypatch.setattr(
        api,
        "bridge_events",
        lambda app=None: {
            "status": "ok",
            "delivery_mode": "shared_database",
            "consumer_active": True,
            "sent": None,
        },
    )

    app = FastAPI()
    api.install_news_agent_network_api(app)
    client = TestClient(app)

    status = client.get("/api/news-agents/status")
    assert status.status_code == 200
    assert status.json()["agents"][0]["id"] == "crypto_ai"
    assert status.json()["bridge"]["delivery_mode"] == "shared_database"
    assert status.json()["bridge"]["consumer_active"] is True
    assert status.json()["bridge"]["sent_count"] is None

    detail = client.get("/api/news-agents/crypto_ai")
    assert detail.status_code == 200
    assert detail.json()["agent"]["id"] == "crypto_ai"

    run = client.post("/api/news-agents/crypto_ai/run")
    assert run.status_code == 200
    assert run.json()["bridge"]["sent"] is None
    assert run.json()["bridge"]["delivery_mode"] == "shared_database"

    page = client.get("/news-agents")
    assert page.status_code == 200
    assert "Specialized News AI Network" in page.text
    assert "Crypto News AI" in page.text
