"""Subsystem News AI agents and News Supervisor.

Each sub-agent owns a category of sources. The supervisor aggregates their load,
coverage, credibility, and action signals so one AI does not carry the entire
news-monitoring workload.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .analyzer import analyze_items, demo_items
from .models import NewsItem, NewsSource
from .sources import default_sources


@dataclass(frozen=True)
class NewsAgentConfig:
    """Configuration for a specialized news AI."""

    id: str
    name: str
    responsibility: str
    categories: tuple[str, ...]
    source_kinds: tuple[str, ...] = ()
    max_items_per_cycle: int = 40


AGENT_CONFIGS: tuple[NewsAgentConfig, ...] = (
    NewsAgentConfig("world_news_ai", "World News AI", "Следит за мировыми новостями и геополитикой.", ("world_news", "world_finance")),
    NewsAgentConfig("finance_crypto_ai", "Finance & Crypto News AI", "Следит за криптой, биржами, рынками и регуляторами.", ("crypto_news", "exchange", "macro_official", "regulation_official", "world_finance")),
    NewsAgentConfig("sports_news_ai", "Sports News AI", "Следит за спортивными новостями.", ("sports",)),
    NewsAgentConfig("weather_news_ai", "Weather & Disaster News AI", "Следит за погодой, штормами, катастрофами и землетрясениями.", ("weather", "weather_disaster")),
    NewsAgentConfig("telegram_news_ai", "Telegram News AI", "Следит за Telegram-источниками из allowlist.", ("telegram_news",), ("telegram",)),
    NewsAgentConfig("x_news_ai", "X News AI", "Следит за X/Twitter источниками из allowlist.", ("x_news",), ("x",)),
    NewsAgentConfig("youtube_news_ai", "YouTube News AI", "Следит за YouTube-источниками и отделяет мнения от фактов.", ("youtube_news",), ("youtube",)),
    NewsAgentConfig("security_news_ai", "Security News AI", "Следит за взломами, уязвимостями и технологическими рисками.", ("security", "tech_security")),
)


def agent_configs_payload() -> list[dict[str, object]]:
    """Return available sub-agent configs."""

    return [
        {
            "id": config.id,
            "name": config.name,
            "responsibility": config.responsibility,
            "categories": list(config.categories),
            "source_kinds": list(config.source_kinds),
            "max_items_per_cycle": config.max_items_per_cycle,
        }
        for config in AGENT_CONFIGS
    ]


def run_news_agents(raw_items: list[dict[str, object]] | None = None) -> dict[str, object]:
    """Run all specialized news agents and aggregate their reports."""

    sources = default_sources()
    items = analyze_items(raw_items or demo_items(), sources=sources)
    reports = [_run_agent(config, sources, items) for config in AGENT_CONFIGS]
    supervisor = _supervisor_report(reports)
    return {
        "status": "ok",
        "supervisor": supervisor,
        "agents": reports,
        "configs": agent_configs_payload(),
    }


def _run_agent(config: NewsAgentConfig, sources: list[NewsSource], items: list[NewsItem]) -> dict[str, object]:
    owned_sources = [source for source in sources if source.category in config.categories or (config.source_kinds and source.kind in config.source_kinds)]
    owned_source_ids = {source.id for source in owned_sources}
    owned_items = [item for item in items if item.source_id in owned_source_ids or item.kind in config.source_kinds]
    urgent = [item for item in owned_items if item.urgency == "high"]
    confirmations = [item for item in owned_items if item.needs_confirmation]
    blocked = [item for item in owned_items if item.ai_action == "BLOCK_BUY"]
    avg_credibility = round(sum(item.credibility_percent for item in owned_items) / max(len(owned_items), 1), 1)
    load_percent = min(round(len(owned_sources) / max(config.max_items_per_cycle, 1) * 100, 1), 100.0)
    health_score = _agent_health(source_count=len(owned_sources), avg_credibility=avg_credibility, blocked=len(blocked), load_percent=load_percent)
    status = "active" if owned_sources else "no_sources"
    if load_percent > 85:
        status = "overloaded"
    if blocked:
        status = "attention"
    return {
        "id": config.id,
        "name": config.name,
        "responsibility": config.responsibility,
        "status": status,
        "health_score": health_score,
        "load_percent": load_percent,
        "source_count": len(owned_sources),
        "item_count": len(owned_items),
        "average_credibility_percent": avg_credibility,
        "high_urgency": len(urgent),
        "needs_confirmation": len(confirmations),
        "block_buy": len(blocked),
        "sources": [source.to_dict() for source in owned_sources[:12]],
        "top_items": [item.to_dict() for item in owned_items[:5]],
        "assessment": _agent_assessment(config.name, len(owned_sources), len(owned_items), avg_credibility, len(confirmations), len(blocked)),
    }


def _supervisor_report(agent_reports: list[dict[str, object]]) -> dict[str, object]:
    total_sources = sum(int(report.get("source_count", 0)) for report in agent_reports)
    total_items = sum(int(report.get("item_count", 0)) for report in agent_reports)
    total_confirmations = sum(int(report.get("needs_confirmation", 0)) for report in agent_reports)
    total_blocked = sum(int(report.get("block_buy", 0)) for report in agent_reports)
    avg_health = round(sum(float(report.get("health_score", 0)) for report in agent_reports) / max(len(agent_reports), 1), 1)
    avg_credibility = round(sum(float(report.get("average_credibility_percent", 0)) for report in agent_reports) / max(len(agent_reports), 1), 1)
    overloaded = [report for report in agent_reports if report.get("status") == "overloaded"]
    attention = [report for report in agent_reports if report.get("status") == "attention"]
    decision = "NORMAL"
    if total_blocked:
        decision = "BLOCK_BUY_AND_VERIFY"
    elif total_confirmations >= 3:
        decision = "VERIFY_BEFORE_ACTION"
    return {
        "id": "main_news_supervisor_ai",
        "name": "Main News Supervisor AI",
        "role": "Контролирует подкатегории новостей, нагрузку, достоверность и итоговое действие AI.",
        "agent_count": len(agent_reports),
        "total_sources": total_sources,
        "total_items": total_items,
        "average_agent_health": avg_health,
        "average_credibility_percent": avg_credibility,
        "needs_confirmation": total_confirmations,
        "block_buy": total_blocked,
        "overloaded_agents": [report["name"] for report in overloaded],
        "attention_agents": [report["name"] for report in attention],
        "decision": decision,
        "assessment": _supervisor_assessment(avg_health, avg_credibility, total_confirmations, total_blocked, overloaded, attention),
    }


def _agent_health(*, source_count: int, avg_credibility: float, blocked: int, load_percent: float) -> int:
    score = 70
    if source_count >= 5:
        score += 10
    if avg_credibility >= 70:
        score += 10
    if avg_credibility < 55:
        score -= 12
    if blocked:
        score -= 8
    if load_percent > 85:
        score -= 12
    return max(min(score, 100), 0)


def _agent_assessment(name: str, source_count: int, item_count: int, credibility: float, confirmations: int, blocked: int) -> str:
    if blocked:
        return f"{name}: есть срочные неподтверждённые сигналы, BUY должен быть заблокирован до проверки."
    if confirmations:
        return f"{name}: часть новостей требует подтверждения, средняя достоверность {credibility:.1f}%."
    if item_count:
        return f"{name}: работает штатно, источников {source_count}, средняя достоверность {credibility:.1f}%."
    return f"{name}: источники назначены, но новых материалов в текущем цикле нет."


def _supervisor_assessment(health: float, credibility: float, confirmations: int, blocked: int, overloaded: list[dict[str, object]], attention: list[dict[str, object]]) -> str:
    if blocked:
        return "Главный News AI: обнаружены рискованные неподтверждённые новости. Торговые BUY-сигналы должны ждать проверки."
    if overloaded:
        return "Главный News AI: часть под-AI перегружена, нужно уменьшить частоту или разделить источники."
    if attention or confirmations:
        return f"Главный News AI: система работает, но {confirmations} новостей требуют подтверждения. Средняя достоверность {credibility:.1f}%."
    return f"Главный News AI: подсистемы работают штатно. Health {health:.1f}%, средняя достоверность {credibility:.1f}%."
