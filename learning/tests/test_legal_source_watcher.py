from __future__ import annotations

from fastapi.testclient import TestClient

from learning.legal_source_watcher import LegalWatchStateStore, legal_source_registry, watch_legal_items, watch_with_store
from learning.legal_watcher_app import app


CRITICAL_ITEM = {
    "title": "Official crypto exchange restriction",
    "topic": "crypto_regulation",
    "source_domain": "sec.gov",
    "source_type": "regulator_docs",
    "url": "https://sec.gov/example/crypto-restriction",
    "summary": "Official new rule says this crypto exchange activity is illegal and must be banned.",
}


def test_legal_source_registry_filters_region() -> None:
    registry = legal_source_registry("us")

    assert registry["status"] == "ok"
    domains = {source["domain"] for source in registry["sources"]}
    assert "sec.gov" in domains
    assert "fatf-gafi.org" in domains
    assert "esma.europa.eu" not in domains


def test_watch_legal_items_creates_alert_and_controller_advice() -> None:
    result = watch_legal_items([CRITICAL_ITEM])

    assert result["status"] == "ok"
    assert result["new_count"] == 1
    assert result["duplicate_count"] == 0
    assert result["alerts"][0]["severity"] == "critical"
    assert result["controller_advice"]["recommended_action"] == "block_action"
    assert result["controller_advice"]["must_notify_owner"] is True
    assert "general_controller" in result["controller_advice"]["affected_bots"]


def test_watch_legal_items_deduplicates_seen_items() -> None:
    first = watch_legal_items([CRITICAL_ITEM])
    second = watch_legal_items([CRITICAL_ITEM], state=first["state"])

    assert second["new_count"] == 0
    assert second["duplicate_count"] == 1
    assert second["controller_advice"]["recommended_action"] == "continue"


def test_watch_with_store_persists_state(tmp_path) -> None:
    store = LegalWatchStateStore(tmp_path / "legal_state.json")

    first = watch_with_store([CRITICAL_ITEM], store)
    second = watch_with_store([CRITICAL_ITEM], store)

    assert first["new_count"] == 1
    assert second["new_count"] == 0
    assert second["duplicate_count"] == 1


def test_legal_watcher_api(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("LEGAL_WATCH_STATE_FILE", str(tmp_path / "legal_state.json"))
    client = TestClient(app)

    sources = client.get("/api/legal/watch/sources?region=us")
    assert sources.status_code == 200
    assert any(source["domain"] == "sec.gov" for source in sources.json()["sources"])

    run = client.post("/api/legal/watch/run", json={"items": [CRITICAL_ITEM]})
    assert run.status_code == 200
    assert run.json()["new_count"] == 1
    assert run.json()["controller_advice"]["recommended_action"] == "block_action"

    repeat = client.post("/api/legal/watch/run", json={"items": [CRITICAL_ITEM]})
    assert repeat.status_code == 200
    assert repeat.json()["new_count"] == 0
    assert repeat.json()["duplicate_count"] == 1
