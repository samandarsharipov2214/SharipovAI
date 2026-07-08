from __future__ import annotations

from fastapi.testclient import TestClient

from learning.material_ingestion import ingest_material, material_to_bot_update
from learning.material_ingestion_app import app
from learning.material_store import MaterialStore


SAMPLE_CONTENT = """
Liquidity and spread are critical before any trade. A market order can suffer slippage when the order book is thin.
Risk management requires position sizing, stop loss planning and drawdown limits.
A bot must reduce confidence when liquidity is weak or when volatility is high.
"""


def test_ingest_material_creates_safe_learning_record() -> None:
    result = ingest_material(
        title="Exchange liquidity lesson",
        source_type="course_note",
        domain="exchanges",
        content=SAMPLE_CONTENT,
    )

    assert result["status"] == "ok"
    material = result["material"]
    assert material["id"].startswith("MAT-")
    assert material["full_text_stored"] is False
    assert len(material["stored_preview"]) <= 700
    assert material["content_digest"]
    assert "paper_trading_bot" in material["assigned_bots"]
    assert material["summary"]
    assert material["rules"]
    assert material["exam"]
    assert "password_hash" not in material


def test_material_to_bot_update_only_for_assigned_bot() -> None:
    material = ingest_material(
        title="Risk note",
        source_type="course_note",
        domain="risk",
        content=SAMPLE_CONTENT,
    )["material"]

    assigned = material_to_bot_update(material, "risk_engine")
    not_assigned = material_to_bot_update(material, "news_agent")

    assert assigned["status"] == "ok"
    assert assigned["rules"]
    assert not_assigned["status"] == "not_assigned"


def test_material_store_create_update_and_filter_by_bot(tmp_path) -> None:
    store = MaterialStore(tmp_path / "materials.json")
    material = ingest_material(
        title="Trading note",
        source_type="course_note",
        domain="trading",
        content=SAMPLE_CONTENT,
    )["material"]

    created = store.add_material(material)
    updated = store.add_material({**material, "title": "Trading note updated"})

    assert created["action"] == "created"
    assert updated["action"] == "updated"
    assert len(store.list_materials()) == 1
    assert store.get_material(material["id"])["title"] == "Trading note updated"
    assert store.materials_for_bot("paper_trading_bot")


def test_material_ingestion_api(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("LEARNING_MATERIALS_FILE", str(tmp_path / "materials.json"))
    client = TestClient(app)

    response = client.post(
        "/api/learning/materials",
        json={
            "title": "Exchange lesson",
            "source_type": "course_note",
            "domain": "exchanges",
            "content": SAMPLE_CONTENT,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    material_id = payload["material"]["id"]

    list_response = client.get("/api/learning/materials")
    assert list_response.json()["count"] == 1

    get_response = client.get(f"/api/learning/materials/{material_id}")
    assert get_response.json()["material"]["id"] == material_id

    bot_response = client.get("/api/learning/materials/bots/paper_trading_bot")
    assert bot_response.json()["count"] == 1
    assert bot_response.json()["updates"][0]["status"] == "ok"
