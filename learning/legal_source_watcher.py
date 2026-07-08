"""Legal source watcher for SharipovAI.

This module compares newly fetched official/regulatory items against a saved
last-seen state. It then converts unseen items into legal alerts and a
General Controller advice package.

It does not fetch the web by itself yet. A future connector should pass fetched
items into `watch_legal_items`.
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any

from .legal_regulatory_monitor import evaluate_legal_change, legal_alert_summary


DEFAULT_LEGAL_SOURCES = [
    {"id": "US-SEC", "region": "us", "domain": "sec.gov", "source_type": "regulator_docs", "topics": ["securities_law", "crypto_regulation", "consumer_protection"]},
    {"id": "US-CFTC", "region": "us", "domain": "cftc.gov", "source_type": "regulator_docs", "topics": ["crypto_regulation", "exchange_rules"]},
    {"id": "US-FINCEN", "region": "us", "domain": "fincen.gov", "source_type": "regulator_docs", "topics": ["aml_kyc"]},
    {"id": "US-IRS", "region": "us", "domain": "irs.gov", "source_type": "official", "topics": ["tax"]},
    {"id": "EU-ESMA", "region": "eu", "domain": "esma.europa.eu", "source_type": "regulator_docs", "topics": ["securities_law", "crypto_regulation"]},
    {"id": "EU-EURLEX", "region": "eu", "domain": "eur-lex.europa.eu", "source_type": "legislation", "topics": ["crypto_regulation", "data_privacy", "aml_kyc"]},
    {"id": "UK-FCA", "region": "uk", "domain": "fca.org.uk", "source_type": "regulator_docs", "topics": ["crypto_regulation", "consumer_protection", "aml_kyc"]},
    {"id": "GLOBAL-FATF", "region": "global", "domain": "fatf-gafi.org", "source_type": "official", "topics": ["aml_kyc", "crypto_regulation"]},
    {"id": "GLOBAL-BIS", "region": "global", "domain": "bis.org", "source_type": "official", "topics": ["financial_institutions", "risk"]},
]


class LegalWatchStateStore:
    """Persist last-seen legal item digests."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"seen": {}, "history": []}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and isinstance(data.get("seen"), dict):
                data.setdefault("history", [])
                return data
        except Exception:
            return {"seen": {}, "history": []}
        return {"seen": {}, "history": []}

    def save(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def legal_source_registry(region: str = "global") -> dict[str, Any]:
    """Return configured official legal/regulatory sources."""

    selected = region.strip().lower() or "global"
    sources = [source for source in DEFAULT_LEGAL_SOURCES if selected == "global" or source["region"] in {selected, "global"}]
    return {"status": "ok", "region": selected, "sources": sources}


def watch_legal_items(items: list[dict[str, Any]], *, state: dict[str, Any] | None = None) -> dict[str, Any]:
    """Compare fetched legal items with state and create alerts for new items."""

    state = {"seen": {}, "history": []} if state is None else state
    seen = state.setdefault("seen", {})
    history = state.setdefault("history", [])
    new_items: list[dict[str, Any]] = []
    duplicate_items: list[dict[str, Any]] = []

    for item in items:
        fingerprint = legal_item_fingerprint(item)
        item_with_id = {**item, "fingerprint": fingerprint}
        if fingerprint in seen:
            duplicate_items.append(item_with_id)
            continue
        seen[fingerprint] = {"first_seen_at": int(time.time()), "title": item.get("title", ""), "source_domain": item.get("source_domain", "")}
        history.append({"fingerprint": fingerprint, "title": item.get("title", ""), "seen_at": int(time.time())})
        new_items.append(item_with_id)

    alerts = [evaluate_legal_change(item) for item in new_items]
    controller_package = controller_advice_package(alerts)
    return {
        "status": "ok",
        "new_count": len(new_items),
        "duplicate_count": len(duplicate_items),
        "new_items": new_items,
        "duplicates": duplicate_items,
        "alerts": alerts,
        "controller_advice": controller_package,
        "state": state,
    }


def watch_with_store(items: list[dict[str, Any]], store: LegalWatchStateStore) -> dict[str, Any]:
    """Run watcher and persist updated state."""

    result = watch_legal_items(items, state=store.load())
    store.save(result["state"])
    return {key: value for key, value in result.items() if key != "state"}


def controller_advice_package(alerts: list[dict[str, Any]]) -> dict[str, Any]:
    """Create a compact package for General Controller."""

    valid_alerts = [alert for alert in alerts if alert.get("status") == "ok"]
    summary = legal_alert_summary(valid_alerts)
    return {
        "target": "general_controller",
        "type": "legal_regulatory_update",
        "created_at": int(time.time()),
        "summary": summary,
        "recommended_action": summary.get("controller_action", "continue"),
        "must_notify_owner": summary.get("controller_action") in {"manual_review", "block_action"},
        "affected_bots": sorted({bot for alert in valid_alerts for bot in alert.get("affected_bots", [])}),
        "instructions": _controller_instructions(summary.get("controller_action", "continue")),
    }


def legal_item_fingerprint(item: dict[str, Any]) -> str:
    """Create stable fingerprint for a legal item."""

    base = "|".join(
        [
            str(item.get("title", "")).strip().lower(),
            str(item.get("source_domain", "")).strip().lower(),
            str(item.get("url", "")).strip().lower(),
            str(item.get("summary", item.get("text", ""))).strip().lower()[:500],
        ]
    )
    return hashlib.sha256(base.encode("utf-8")).hexdigest()


def _controller_instructions(action: str) -> list[str]:
    if action == "block_action":
        return [
            "Block related trading or access actions until manual legal review.",
            "Notify owner immediately.",
            "Lower confidence for all affected bots.",
            "Create a learning material from the legal alert.",
        ]
    if action == "manual_review":
        return [
            "Pause risky decisions in affected domains.",
            "Request owner/manual review.",
            "Ask News Agent and Risk Engine for cross-check.",
        ]
    if action == "caution":
        return [
            "Allow only low-risk actions.",
            "Require extra source confirmation.",
            "Update affected bot rules.",
        ]
    if action == "watch":
        return [
            "Continue monitoring.",
            "Reduce confidence slightly for affected topics.",
        ]
    return ["No immediate legal action required. Continue monitoring."]
