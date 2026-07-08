from __future__ import annotations

from fastapi.testclient import TestClient

from learning.legal_feed_fetcher import legal_feed_registry, parse_feed_entries, run_legal_monitor_cycle
from learning.legal_monitor_cycle_app import app
from learning.legal_source_watcher import LegalWatchStateStore


RSS_XML = """<?xml version="1.0" encoding="UTF-8" ?>
<rss version="2.0">
  <channel>
    <title>Regulator News</title>
    <item>
      <title>Official crypto exchange ban</title>
      <link>https://sec.gov/news/crypto-ban</link>
      <description>Official new rule says crypto exchange activity is illegal and banned.</description>
      <pubDate>Wed, 09 Jul 2026 10:00:00 GMT</pubDate>
    </item>
  </channel>
</rss>
"""


FEED = {
    "id": "TEST-SEC",
    "region": "us",
    "source_domain": "sec.gov",
    "source_type": "regulator_docs",
    "topic": "crypto_regulation",
    "url": "https://sec.gov/test.rss",
}


def test_parse_feed_entries_to_legal_items() -> None:
    entries = parse_feed_entries(RSS_XML, FEED)

    assert len(entries) == 1
    assert entries[0]["title"] == "Official crypto exchange ban"
    assert entries[0]["source_domain"] == "sec.gov"
    assert entries[0]["topic"] == "crypto_regulation"
    assert entries[0]["entry_id"]


def test_legal_feed_registry_returns_feeds_and_sources() -> None:
    registry = legal_feed_registry("us")

    assert registry["status"] == "ok"
    assert registry["feeds"]
    assert any(feed["source_domain"] == "sec.gov" for feed in registry["feeds"])
    assert any(source["domain"] == "sec.gov" for source in registry["sources"])


def test_run_legal_monitor_cycle_generates_advice_and_learning_material(tmp_path) -> None:
    store = LegalWatchStateStore(tmp_path / "legal_state.json")
    items = parse_feed_entries(RSS_XML, FEED)

    result = run_legal_monitor_cycle(store=store, fetched_items=items)

    assert result["status"] == "ok"
    assert result["item_count"] == 1
    assert result["watch"]["new_count"] == 1
    assert result["controller_advice"]["recommended_action"] == "block_action"
    assert result["learning_materials"]
    assert result["learning_materials"][0]["status"] == "ok"
    assert result["learning_materials"][0]["material"]["full_text_stored"] is False


def test_run_legal_monitor_cycle_deduplicates_second_run(tmp_path) -> None:
    store = LegalWatchStateStore(tmp_path / "legal_state.json")
    items = parse_feed_entries(RSS_XML, FEED)

    first = run_legal_monitor_cycle(store=store, fetched_items=items)
    second = run_legal_monitor_cycle(store=store, fetched_items=items)

    assert first["watch"]["new_count"] == 1
    assert second["watch"]["new_count"] == 0
    assert second["watch"]["duplicate_count"] == 1
    assert second["controller_advice"]["recommended_action"] == "continue"


def test_legal_monitor_cycle_api(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("LEGAL_WATCH_STATE_FILE", str(tmp_path / "legal_state.json"))
    client = TestClient(app)
    items = parse_feed_entries(RSS_XML, FEED)

    feeds_response = client.get("/api/legal/cycle/feeds?region=us")
    assert feeds_response.status_code == 200
    assert feeds_response.json()["feeds"]

    run_response = client.post("/api/legal/cycle/run", json={"items": items, "use_live_feeds": False})
    assert run_response.status_code == 200
    payload = run_response.json()
    assert payload["watch"]["new_count"] == 1
    assert payload["controller_advice"]["recommended_action"] == "block_action"
