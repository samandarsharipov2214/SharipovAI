from __future__ import annotations

from fastapi.testclient import TestClient

from learning.legal_source_watcher import LegalWatchStateStore
from learning.policy_dashboard_app import app
from learning.policy_journal import PolicyJournal
from learning.policy_ops import run_policy_ops


ITEM = {
    "title": "Official crypto restriction",
    "topic": "crypto_regulation",
    "source_domain": "sec.gov",
    "source_type": "regulator_docs",
    "url": "https://sec.gov/example/restriction",
    "summary": "Official rule says crypto exchange activity is illegal and banned.",
}


def test_policy_journal_stores_alerts_and_advice(tmp_path) -> None:
    journal = PolicyJournal(tmp_path / "policy.json")
    alert = {
        "status": "ok",
        "title": "Official crypto restriction",
        "topic": "crypto_regulation",
        "severity": "critical",
        "confidence": "high",
        "source_domain": "sec.gov",
        "affected_bots": ["general_controller", "risk_engine"],
        "general_controller_advice": {"action": "block_action"},
    }

    first = journal.add([alert], {"recommended_action": "block_action", "must_notify_owner": True})
    second = journal.add([alert], {"recommended_action": "block_action", "must_notify_owner": True})
    snap = journal.snapshot()

    assert first["created"] == 1
    assert second["created"] == 0
    assert snap["stats"]["alert_count"] == 1
    assert snap["latest_advice"]["recommended_action"] == "block_action"


def test_policy_ops_runs_cycle_and_persists_journal(tmp_path) -> None:
    watch_store = LegalWatchStateStore(tmp_path / "watch.json")
    journal = PolicyJournal(tmp_path / "policy.json")

    result = run_policy_ops(watch_store=watch_store, journal=journal, items=[ITEM])

    assert result["status"] == "ok"
    assert result["cycle"]["watch"]["new_count"] == 1
    assert result["journal"]["created"] == 1
    assert result["snapshot"]["stats"]["alert_count"] == 1
    assert result["snapshot"]["latest_advice"]["recommended_action"] == "block_action"


def test_policy_dashboard_api_and_page(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("LEGAL_WATCH_STATE_FILE", str(tmp_path / "watch.json"))
    monkeypatch.setenv("POLICY_JOURNAL_FILE", str(tmp_path / "policy.json"))
    client = TestClient(app)

    run = client.post("/api/policy-monitor/run", json={"items": [ITEM]})
    assert run.status_code == 200
    assert run.json()["journal"]["created"] == 1

    snapshot = client.get("/api/policy-monitor/snapshot")
    assert snapshot.status_code == 200
    assert snapshot.json()["stats"]["alert_count"] == 1

    page = client.get("/policy-monitor")
    assert page.status_code == 200
    assert "Legal / Policy Monitor" in page.text
    assert "Official crypto restriction" in page.text
