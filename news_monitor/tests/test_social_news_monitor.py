"""Tests for Social News Monitor."""

from __future__ import annotations

from news_monitor.analyzer import analyzed_news_payload, analyze_items
from news_monitor.sources import sources_payload


def test_sources_include_social_and_rss_definitions() -> None:
    """Default sources should cover RSS, Telegram, X, and official sources."""

    payload = sources_payload()
    kinds = set(payload["grouped"])

    assert payload["total"] >= 10
    assert {"rss", "telegram", "x", "official"}.issubset(kinds)
    assert payload["requires_credentials"] >= 1


def test_analyzer_blocks_unconfirmed_high_urgency_social_news() -> None:
    """A single high-urgency social post should require confirmation and block BUY."""

    items = analyze_items([
        {
            "source_id": "watcher_guru_x",
            "title": "Breaking: BTC hack and liquidation alert",
            "summary": "Unconfirmed social report about BTC market risk.",
        }
    ])

    assert len(items) == 1
    item = items[0]
    assert item.urgency == "high"
    assert item.needs_confirmation is True
    assert item.ai_action == "BLOCK_BUY"
    assert "BTC" in item.symbols


def test_analyzer_allows_analysis_when_official_and_confirmed() -> None:
    """Official/high-trust bullish news can be used for analysis when confirmed."""

    items = analyze_items([
        {"source_id": "bybit_announcements", "title": "BTC listing partnership and market upgrade"},
        {"source_id": "cointelegraph_rss", "title": "Bitcoin ETF inflow supports BTC market upgrade"},
    ])

    assert items
    assert any(item.confirmation_count >= 2 for item in items if "BTC" in item.symbols)
    assert any(item.ai_action in {"ALLOW_ANALYSIS_ONLY", "WATCH"} for item in items)


def test_analyzed_news_payload_contains_alerts_and_rules() -> None:
    """API payload should include summary, items, alerts, and safety rules."""

    payload = analyzed_news_payload()

    assert payload["status"] == "ok"
    assert payload["summary"]["total"] > 0
    assert payload["items"]
    assert payload["rules"]
    assert any("Telegram/X" in rule for rule in payload["rules"])
