"""Tests for subsystem News AI agents."""

from __future__ import annotations

from news_monitor.agents import agent_configs_payload, run_news_agents
from news_monitor.sources import sources_payload


def test_agent_configs_include_required_subsystems() -> None:
    """News monitor should have specialized sub-AI configs."""

    configs = agent_configs_payload()
    ids = {config["id"] for config in configs}

    assert "world_news_ai" in ids
    assert "politics_government_ai" in ids
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
    names = {source["name"] for source in payload["sources"]}

    assert payload["total"] >= 75
    assert "world_news" in categories
    assert "politics_official" in categories
    assert "international_official" in categories
    assert "sports" in categories
    assert "weather" in categories
    assert "telegram_news" in categories
    assert "x_news" in categories
    assert "youtube_news" in categories
    assert "security" in categories
    assert "White House Briefing Room" in names
    assert "State Duma News" in names
    assert "Kremlin Events" in names
    assert "European Commission Press Corner" in names
    assert "United Nations News" in names
    assert "NATO News" in names


def test_news_agents_return_supervisor_report() -> None:
    """Running news agents should produce sub-agent and supervisor reports."""

    report = run_news_agents([
        {"source_id": "watcher_guru_x", "title": "Breaking: BTC hack liquidation alert"},
        {"source_id": "bbc_world", "title": "World market update as central banks discuss policy"},
        {"source_id": "espn_top", "title": "Major sports update from football league"},
        {"source_id": "noaa_alerts", "title": "Urgent weather alert for severe storm"},
        {"source_id": "white_house_briefing", "title": "Official White House statement on market policy"},
    ])

    assert report["status"] == "ok"
    assert report["supervisor"]["name"] == "Main News Supervisor AI"
    assert report["supervisor"]["agent_count"] >= 9
    assert report["agents"]
    assert any(agent["id"] == "x_news_ai" for agent in report["agents"])
    assert any(agent["id"] == "weather_news_ai" for agent in report["agents"])
    assert any(agent["id"] == "politics_government_ai" for agent in report["agents"])
    assert report["supervisor"]["decision"] in {"NORMAL", "VERIFY_BEFORE_ACTION", "BLOCK_BUY_AND_VERIFY"}


def test_politics_government_agent_owns_official_sources() -> None:
    """Politics agent should own official government and international organization sources."""

    report = run_news_agents([
        {"source_id": "white_house_briefing", "title": "Official White House economic policy statement"},
        {"source_id": "duma_news", "title": "State Duma official statement on digital assets"},
        {"source_id": "un_news", "title": "United Nations official statement on global crisis"},
    ])
    politics = next(agent for agent in report["agents"] if agent["id"] == "politics_government_ai")
    source_names = {source["name"] for source in politics["sources"]}

    assert politics["source_count"] >= 20
    assert politics["item_count"] >= 3
    assert "White House Briefing Room" in source_names
    assert "State Duma News" in source_names
    assert politics["average_credibility_percent"] >= 70


def test_supervisor_blocks_buy_when_subagent_finds_risky_social_news() -> None:
    """Supervisor should block buy when a sub-agent flags risky unconfirmed news."""

    report = run_news_agents([
        {"source_id": "watcher_guru_x", "title": "Breaking: BTC hack liquidation alert"},
    ])

    assert report["supervisor"]["decision"] == "BLOCK_BUY_AND_VERIFY"
    assert report["supervisor"]["block_buy"] >= 1
    assert "X News AI" in report["supervisor"]["attention_agents"]
