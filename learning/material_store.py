"""Safe JSON store for ingested learning materials."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class MaterialStore:
    """Persist safe learning material records without full source text."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def list_materials(self) -> list[dict[str, Any]]:
        return list(self._load().get("materials", []))

    def add_material(self, material: dict[str, Any]) -> dict[str, Any]:
        data = self._load()
        materials = data.setdefault("materials", [])
        existing_index = self._find_index(material.get("id"), materials)
        if existing_index >= 0:
            materials[existing_index] = material
            action = "updated"
        else:
            materials.append(material)
            action = "created"
        self._save(data)
        return {"status": "ok", "action": action, "material": material}

    def get_material(self, material_id: str) -> dict[str, Any] | None:
        for material in self.list_materials():
            if material.get("id") == material_id:
                return material
        return None

    def materials_for_bot(self, bot_name: str) -> list[dict[str, Any]]:
        bot = bot_name.strip().lower().replace("-", "_").replace(" ", "_")
        return [material for material in self.list_materials() if bot in material.get("assigned_bots", [])]

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"materials": []}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and isinstance(data.get("materials"), list):
                return data
        except Exception:
            return {"materials": []}
        return {"materials": []}

    def _save(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    @staticmethod
    def _find_index(material_id: str | None, materials: list[dict[str, Any]]) -> int:
        for index, material in enumerate(materials):
            if material_id and material.get("id") == material_id:
                return index
        return -1
