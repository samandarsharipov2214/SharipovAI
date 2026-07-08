"""Tests for subsystem News AI agents."""

from __future__ import annotations

from news_monitor.agents import agent_configs_payload, run_news_agents
from news_monitor.sources import sources_payload


def test_agent_configs_include_required_subsystems() -> None:
    """News monitor should have specialized sub-AI configs."""

    configs = agent_configs_payload()
    ids = {config["id"] for config in configs}

    assert "world_news_ai" in ids
    assert "finance_crypto_ai" in ids
    assert "sports_news_ai" in ids
    assert "weather_news_ai" in ids
    assert "telegram_news_ai" in ids
    assert "x_news_ai" in ids
    assert "youtube_news_ai" in ids
    assert "security_news_ai" in ids


def test_sources_are_grouped_by_category_for_agents() -> None:
    """Expanded sources should be grouped by categories used by agents."""

    payload = sources_payload()
    categories = set(payload["by_category"])

    assert payload["total"] >= 50
    assert "world_news" in categories
    assert "sports" in categories
    assert "weather" in categories
    assert "telegram_news" in categories
    assert "x_news" in categories
    assert "youtube_news" in categories
    assert "security" in categories


def test_news_agents_return_supervisor_report() -> None:
    """Running news agents should produce sub-agent and supervisor reports."""

    report = run_news_agents([
        {"source_id": "watcher_guru_x", "title": "Breaking: BTC hack liquidation alert"},
        {"source_id": "bbc_world", "title": "World market update as central banks discuss policy"},
        {"source_id": "espn_top", "title": "Major sports update from football league"},
        {"source_id": "noaa_alerts", "title": "Urgent weather alert for severe storm"},
    ])

    assert report["status"] == "ok"
    assert report["supervisor"]["name"] == "Main News Supervisor AI"
    assert report["supervisor"]["agent_count"] >= 8
    assert report["agents"]
    assert any(agent["id"] == "x_news_ai" for agent in report["agents"])
    assert any(agent["id"] == "weather_news_ai" for agent in report["agents"])
    assert report["supervisor"]["decision"] in {"NORMAL", "VERIFY_BEFORE_ACTION", "BLOCK_BUY_AND_VERIFY"}


def test_supervisor_blocks_buy_when_subagent_finds_risky_social_news() -> None:
    """Supervisor should block buy when a sub-agent flags risky unconfirmed news."""

    report = run_news_agents([
        {"source_id": "watcher_guru_x", "title": "Breaking: BTC hack liquidation alert"},
    ])

    assert report["supervisor"]["decision"] == "BLOCK_BUY_AND_VERIFY"
    assert report["supervisor"]["block_buy"] >= 1
    assert "X News AI" in report["supervisor"]["attention_agents"]
