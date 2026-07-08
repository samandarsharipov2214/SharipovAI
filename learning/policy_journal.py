"""Policy alert journal for SharipovAI."""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any


class PolicyJournal:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def add(self, alerts: list[dict[str, Any]], advice: dict[str, Any] | None = None) -> dict[str, Any]:
        data = self._load()
        known = {item.get("id") for item in data["alerts"]}
        created = 0
        for alert in alerts:
            if alert.get("status") != "ok":
                continue
            record = _record(alert)
            if record["id"] in known:
                continue
            data["alerts"].append(record)
            known.add(record["id"])
            created += 1
        if advice:
            data["advice"].append({**advice, "stored_at": int(time.time())})
        self._save(data)
        return {"status": "ok", "created": created, "alert_count": len(data["alerts"]), "advice_count": len(data["advice"])}

    def snapshot(self, limit: int = 20) -> dict[str, Any]:
        data = self._load()
        alerts = sorted(data["alerts"], key=lambda item: int(item.get("stored_at", 0)), reverse=True)
        latest_advice = data["advice"][-1] if data["advice"] else None
        return {"status": "ok", "alerts": alerts[:limit], "latest_advice": latest_advice, "stats": _stats(data)}

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"alerts": [], "advice": []}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                data.setdefault("alerts", [])
                data.setdefault("advice", [])
                return data
        except Exception:
            pass
        return {"alerts": [], "advice": []}

    def _save(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _record(alert: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": _id(alert),
        "stored_at": int(time.time()),
        "title": alert.get("title", ""),
        "topic": alert.get("topic", "unknown"),
        "severity": alert.get("severity", "info"),
        "confidence": alert.get("confidence", "low"),
        "source_domain": alert.get("source_domain", ""),
        "affected_bots": alert.get("affected_bots", []),
        "controller_action": alert.get("general_controller_advice", {}).get("action", "continue"),
    }


def _id(alert: dict[str, Any]) -> str:
    raw = "|".join([str(alert.get("title", "")), str(alert.get("topic", "")), str(alert.get("source_domain", ""))])
    return "PJ-" + hashlib.sha256(raw.lower().encode("utf-8")).hexdigest()[:16].upper()


def _stats(data: dict[str, Any]) -> dict[str, Any]:
    by_severity: dict[str, int] = {}
    for alert in data["alerts"]:
        severity = str(alert.get("severity", "unknown"))
        by_severity[severity] = by_severity.get(severity, 0) + 1
    return {"alert_count": len(data["alerts"]), "advice_count": len(data["advice"]), "by_severity": by_severity}
