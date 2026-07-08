"""Tests for Social News Monitor."""

from __future__ import annotations

from news_monitor.analyzer import analyzed_news_payload, analyze_items
from news_monitor.credibility import error_risk, truth_probability, verification_status
from news_monitor.sources import sources_payload


def test_sources_include_large_news_allowlist() -> None:
    """Default sources should cover broad RSS, Telegram, X, and official sources."""

    payload = sources_payload()
    kinds = set(payload["grouped"])
    names = {source["name"] for source in payload["sources"]}

    assert payload["total"] >= 20
    assert {"rss", "telegram", "x", "official"}.issubset(kinds)
    assert payload["requires_credentials"] >= 1
    assert "Reuters Markets" in names
    assert "Federal Reserve Press Releases" in names
    assert "SEC Press Releases" in names
    assert "CISA Alerts" in names


def test_credibility_scoring_penalizes_unconfirmed_social_news() -> None:
    """A single social post should have lower credibility and require verification."""

    probability = truth_probability(trust_score=58, kind="x", confirmation_count=1, urgency="high", tags=["liquidation"])

    assert probability < 55
    assert error_risk(probability) == "высокий"
    assert verification_status(probability, 1, True) == "нужно подтверждение"


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
    assert item.credibility_percent < 60
    assert item.error_risk in {"повышенный", "высокий"}
    assert item.verification_status == "нужно подтверждение"
    assert "BTC" in item.symbols


def test_analyzer_scores_official_confirmed_news_higher() -> None:
    """Official/high-trust confirmed news should get stronger credibility."""

    items = analyze_items([
        {"source_id": "bybit_announcements", "title": "BTC listing partnership and market upgrade"},
        {"source_id": "cointelegraph_rss", "title": "Bitcoin ETF inflow supports BTC market upgrade"},
    ])

    assert items
    official = next(item for item in items if item.source_id == "bybit_announcements")
    assert official.confirmation_count >= 2
    assert official.credibility_percent >= 80
    assert any(item.ai_action in {"ALLOW_ANALYSIS_ONLY", "WATCH"} for item in items)


def test_analyzed_news_payload_contains_credibility_summary() -> None:
    """API payload should include credibility summary and per-item scores."""

    payload = analyzed_news_payload()

    assert payload["status"] == "ok"
    assert payload["summary"]["total"] > 0
    assert "average_credibility_percent" in payload["summary"]
    assert "low_credibility" in payload["summary"]
    assert payload["items"]
    assert "credibility_percent" in payload["items"][0]
    assert "error_risk" in payload["items"][0]
    assert payload["rules"]
    assert any("Telegram/X" in rule for rule in payload["rules"])
