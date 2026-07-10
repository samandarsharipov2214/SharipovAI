from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from persistence_paths import durable_data_path

from .models import FinalDecision


class DecisionStore:
    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path else durable_data_path(
            "GENERAL_CONTROLLER_DECISIONS_FILE",
            "data/general_controller_decisions.jsonl",
        )

    def append(self, decision: FinalDecision) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(asdict(decision), ensure_ascii=False) + "\n")

    def list(self, limit: int = 50) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        items: list[dict[str, Any]] = []
        for line in self.path.read_text(encoding="utf-8").splitlines()[-max(1, min(limit, 500)) :]:
            try:
                items.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return list(reversed(items))
