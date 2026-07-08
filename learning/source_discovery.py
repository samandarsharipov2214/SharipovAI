"""Autonomous source discovery planner for SharipovAI Learning Engine.

The planner does not pirate books or paid articles. It creates search tasks,
source candidates and validation rules so a future connector can search the web
or approved databases safely.
"""

from __future__ import annotations

import time
from typing import Any

from .financial_knowledge_library import BOT_DOMAIN_MAP, DOMAINS


ALLOWED_SOURCE_CLASSES = {
    "official",
    "open_access",
    "exchange_docs",
    "regulator_docs",
    "public_course",
    "book_metadata",
    "whitepaper",
}

BLOCKED_SOURCE_CLASSES = {
    "pirated_book",
    "paid_article_fulltext",
    "leaked_report",
    "unknown_copyright_fulltext",
}

TRUSTED_DOMAINS_BY_TOPIC = {
    "crypto": ["bitcoin.org", "ethereum.org", "binance.com", "coinbase.com", "kraken.com"],
    "stocks": ["sec.gov", "investor.gov", "nasdaq.com", "nyse.com"],
    "exchanges": ["nasdaq.com", "nyse.com", "cmegroup.com", "binance.com", "coinbase.com", "kraken.com"],
    "trading": ["investor.gov", "finra.org", "cmegroup.com", "nasdaq.com"],
    "financial_institutions": ["bis.org", "imf.org", "worldbank.org", "federalreserve.gov"],
    "macro": ["federalreserve.gov", "ecb.europa.eu", "bis.org", "imf.org", "worldbank.org"],
    "risk": ["bis.org", "cmegroup.com", "finra.org", "investor.gov"],
    "regulation": ["sec.gov", "cftc.gov", "finra.org", "esma.europa.eu", "fca.org.uk"],
}


def discovery_plan(bot_name: str | None = None) -> dict[str, Any]:
    """Create a source-discovery plan for one bot or all bots."""

    bots = [bot_name.strip().lower().replace("-", "_").replace(" ", "_")] if bot_name else sorted(BOT_DOMAIN_MAP)
    plans = []
    for bot in bots:
        domains = BOT_DOMAIN_MAP.get(bot)
        if not domains:
            plans.append({"status": "not_found", "bot": bot})
            continue
        plans.append(
            {
                "status": "ok",
                "bot": bot,
                "domains": domains,
                "search_tasks": _search_tasks(bot, domains),
                "source_policy": source_policy(),
            }
        )
    return {"status": "ok", "created_at": int(time.time()), "plans": plans}


def source_policy() -> dict[str, Any]:
    """Return legal and safety rules for source discovery."""

    return {
        "allowed_source_classes": sorted(ALLOWED_SOURCE_CLASSES),
        "blocked_source_classes": sorted(BLOCKED_SOURCE_CLASSES),
        "rules": [
            "Prefer official, regulator, exchange, university and open-access sources.",
            "Never store full copyrighted books or paid articles unless user has rights and uploads them privately.",
            "Store metadata, short summaries, rules, citations and exam questions instead of full text.",
            "For books, store title, author, topic and learning objectives unless the text is legally available.",
            "For trading decisions, use at least two independent sources when facts are market-moving.",
        ],
    }


def validate_source_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
    """Validate a discovered source candidate before ingestion."""

    source_class = str(candidate.get("source_class", "")).strip().lower()
    title = str(candidate.get("title", "")).strip()
    url = str(candidate.get("url", "")).strip()
    domain = str(candidate.get("domain", "")).strip().lower()

    if not title:
        return {"status": "rejected", "reason": "missing_title"}
    if source_class in BLOCKED_SOURCE_CLASSES:
        return {"status": "rejected", "reason": "blocked_source_class", "source_class": source_class}
    if source_class not in ALLOWED_SOURCE_CLASSES:
        return {"status": "needs_review", "reason": "unknown_source_class", "source_class": source_class}
    if not url and source_class != "book_metadata":
        return {"status": "needs_review", "reason": "missing_url"}
    trust_score = _trust_score(domain, source_class)
    return {"status": "accepted", "trust_score": trust_score, "source_class": source_class, "domain": domain}


def rank_source_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Validate and rank candidates by trust score."""

    ranked: list[dict[str, Any]] = []
    for candidate in candidates:
        validation = validate_source_candidate(candidate)
        ranked.append({**candidate, "validation": validation})
    return sorted(ranked, key=lambda item: item["validation"].get("trust_score", 0), reverse=True)


def _search_tasks(bot: str, domains: list[str]) -> list[dict[str, Any]]:
    tasks: list[dict[str, Any]] = []
    for domain in domains:
        tasks.extend(_domain_tasks(bot, domain))
    return tasks


def _domain_tasks(bot: str, domain: str) -> list[dict[str, Any]]:
    trusted_domains = TRUSTED_DOMAINS_BY_TOPIC.get(domain, [])
    domain_description = DOMAINS.get(domain, domain)
    base_queries = [
        f"{domain} official guide risk basics",
        f"{domain} open access research market structure",
        f"{domain} trading risk management educational material",
    ]
    if domain == "crypto":
        base_queries += ["bitcoin whitepaper", "ethereum documentation", "crypto exchange risk liquidation funding rate"]
    if domain == "stocks":
        base_queries += ["SEC investor education stocks financial statements", "equity valuation basics open course"]
    if domain == "financial_institutions":
        base_queries += ["BIS financial institutions clearing settlement", "IMF financial markets institutions guide"]
    if domain == "regulation":
        base_queries += ["SEC crypto securities regulation investor protection", "CFTC digital assets guidance"]

    return [
        {
            "id": f"DISC-{bot}-{domain}-{index}",
            "bot": bot,
            "domain": domain,
            "domain_description": domain_description,
            "query": query,
            "preferred_domains": trusted_domains,
            "allowed_source_classes": sorted(ALLOWED_SOURCE_CLASSES),
            "output": "metadata_summary_rules_exam",
        }
        for index, query in enumerate(base_queries, 1)
    ]


def _trust_score(domain: str, source_class: str) -> int:
    score = 50
    if source_class in {"official", "regulator_docs", "exchange_docs", "whitepaper"}:
        score += 25
    if source_class in {"open_access", "public_course"}:
        score += 15
    for trusted_domains in TRUSTED_DOMAINS_BY_TOPIC.values():
        if domain in trusted_domains:
            score += 20
            break
    return min(score, 100)
