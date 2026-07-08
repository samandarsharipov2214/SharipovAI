"""Legal alert journal store for SharipovAI."""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any


class LegalAlertStore:
    """Persist legal alerts and controller advice packages."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def list_alerts(self, *, limit: int | None = None, severity: str | None = None) -> list[dict[str, Any]]:
        alerts = list(self._load().get("alerts", []))
        if severity:
            alerts = [alert for alert in alerts if alert.get("severity") == severity]
        alerts = sorted(alerts, key=lambda item: int(item.get("stored_at", 0)), reverse=True)
        return alerts[:limit] if limit else alerts

    def add_alerts(self, alerts: list[dict[str, Any]]) -> dict[str, Any]:
        data = self._load()
        existing_ids = {alert.get("alert_id") for alert in data.setdefault("alerts", [])}
        created = 0
        for alert in alerts:
            if alert.get("status") != "ok":
                continue
            normalized = normalize_alert(alert)
            if normalized["alert_id"] in existing_ids:
                continue
            data["alerts"].append(normalized)
            existing_ids.add(normalized["alert_id"])
            created += 1
        data["updated_at"] = int(time.time())
        self._save(data)
        return {"status": "ok", "created": created, "count": len(data["alerts"])}

    def add_controller_advice(self, advice: dict[str, Any]) -> dict[str, Any]:
        data = self._load()
        journal = data.setdefault("controller_advice", [])
        record = {**advice, "advice_id": advice_id(advice), "stored_at": int(time.time())}
        if not any(item.get("advice_id") == record["advice_id"] for item in journal):
            journal.append(record)
        data["updated_at"] = int(time.time())
        self._save(data)
        return {"status": "ok", "advice_id": record["advice_id"], "count": len(journal)}

    def latest_controller_advice(self) -> dict[str, Any] | None:
        journal = list(self._load().get("controller_advice", []))
        if not journal:
            return None
        return sorted(journal, key=lambda item: int(item.get("stored_at", 0)), reverse=True)[0]

    def stats(self) -> dict[str, Any]:
        data = self._load()
        alerts = data.get("alerts", [])
        by_severity: dict[str, int] = {}
        for alert in alerts:
            severity = str(alert.get("severity", "unknown"))
            by_severity[severity] = by_severity.get(severity, 0) + 1
        latest = self.latest_controller_advice()
        return {
            "status": "ok",
            "alert_count": len(alerts),
            "by_severity": by_severity,
            "controller_advice_count": len(data.get("controller_advice", [])),
            "latest_recommended_action": (latest or {}).get("recommended_action", "continue"),
        }

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"alerts": [], "controller_advice": []}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                data.setdefault("alerts", [])
                data.setdefault("controller_advice", [])
                return data
        except Exception:
            return {"alerts": [], "controller_advice": []}
        return {"alerts": [], "controller_advice": []}

    def _save(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def normalize_alert(alert: dict[str, Any]) -> dict[str, Any]:
    """Create a stable stored alert record."""

    record = {
        "alert_id": alert_id(alert),
        "stored_at": int(time.time()),
        "title": alert.get("title", ""),
        "topic": alert.get("topic", "unknown"),
        "severity": alert.get("severity", "info"),
        "confidence": alert.get("confidence", "low"),
        "source_domain": alert.get("source_domain", ""),
        "source_type": alert.get("source_type", ""),
        "official_source": bool(alert.get("official_source", False)),
        "affected_bots": alert.get("affected_bots", []),
        "general_controller_advice": alert.get("general_controller_advice", {}),
    }
    return record


def alert_id(alert: dict[str, Any]) -> str:
    raw = "|".join([str(alert.get("title", "")), str(alert.get("source_domain", "")), str(alert.get("topic", "")), str(alert.get("severity", ""))])
    return "LA-" + hashlib.sha256(raw.lower().encode("utf-8")).hexdigest()[:16].upper()


def advice_id(advice: dict[str, Any]) -> str:
    raw = "|".join([str(advice.get("recommended_action", "")), str(advice.get("created_at", "")), str(advice.get("affected_bots", ""))])
    return "ADV-" + hashlib.sha256(raw.lower().encode("utf-8")).hexdigest()[:16].upper()
