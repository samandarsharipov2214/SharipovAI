"""SharipovAI material ingestion API.

Run with:
    python -m uvicorn learning.material_ingestion_app:app --reload
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from fastapi import Body, FastAPI

from .material_ingestion import ingest_material, material_to_bot_update
from .material_store import MaterialStore


app = FastAPI(title="SharipovAI Material Ingestion")


def material_store() -> MaterialStore:
    path = Path(os.getenv("LEARNING_MATERIALS_FILE", "data/learning_materials.json"))
    return MaterialStore(path)


@app.post("/api/learning/materials")
def ingest_material_api(payload: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
    result = ingest_material(
        title=str(payload.get("title", "")),
        source_type=str(payload.get("source_type", "user_uploaded_file")),
        domain=str(payload.get("domain", "trading")),
        content=str(payload.get("content", "")),
        bots=[str(bot) for bot in payload.get("bots", [])] if isinstance(payload.get("bots"), list) else None,
        rights=str(payload.get("rights", "user_provided_for_private_learning")),
    )
    if result.get("status") != "ok":
        return result
    saved = material_store().add_material(result["material"])
    return {"status": "ok", "action": saved["action"], "material": saved["material"]}


@app.get("/api/learning/materials")
def list_materials_api() -> dict[str, Any]:
    materials = material_store().list_materials()
    return {"status": "ok", "count": len(materials), "materials": materials}


@app.get("/api/learning/materials/{material_id}")
def get_material_api(material_id: str) -> dict[str, Any]:
    material = material_store().get_material(material_id)
    if not material:
        return {"status": "not_found", "material_id": material_id}
    return {"status": "ok", "material": material}


@app.get("/api/learning/materials/bots/{bot_name}")
def materials_for_bot_api(bot_name: str) -> dict[str, Any]:
    materials = material_store().materials_for_bot(bot_name)
    updates = [material_to_bot_update(material, bot_name) for material in materials]
    return {"status": "ok", "bot": bot_name, "count": len(updates), "updates": updates}
