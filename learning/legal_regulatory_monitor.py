"""Legal and regulatory monitor for SharipovAI.

This module plans and evaluates legal/regulatory intelligence for crypto,
stocks, exchanges and financial activity. It is not legal advice. It produces
risk alerts and recommendations for the General Controller.
"""

from __future__ import annotations

import time
from typing import Any


LEGAL_TOPICS = {
    "crypto_regulation": "Криптоактивы, токены, стейблкоины, биржи, custody, DeFi.",
    "securities_law": "Акции, ценные бумаги, раскрытие информации, манипуляции рынком.",
    "exchange_rules": "Правила бирж, листинг, делистинг, торговые ограничения.",
    "aml_kyc": "KYC, AML, санкции, проверка клиентов и источников средств.",
    "tax": "Налоги на инвестиции, крипту, дивиденды, прирост капитала.",
    "consumer_protection": "Защита инвесторов, предупреждения регуляторов, мошенничество.",
    "data_privacy": "Персональные данные, хранение логов, безопасность аккаунтов.",
}


REGULATORY_SOURCES = {
    "us": ["sec.gov", "cftc.gov", "finra.org", "federalreserve.gov", "irs.gov", "treasury.gov", "fincen.gov"],
    "eu": ["esma.europa.eu", "eba.europa.eu", "ecb.europa.eu", "eur-lex.europa.eu"],
    "uk": ["fca.org.uk", "bankofengland.co.uk", "legislation.gov.uk"],
    "global": ["bis.org", "imf.org", "worldbank.org", "fatf-gafi.org", "iosco.org"],
}


SEVERITY_ORDER = {"info": 1, "watch": 2, "caution": 3, "high": 4, "critical": 5}


def legal_monitor_plan(region: str = "global") -> dict[str, Any]:
    """Return monitoring plan for legal and regulatory changes."""

    selected_region = region.strip().lower() or "global"
    sources = sorted(set(REGULATORY_SOURCES.get(selected_region, []) + REGULATORY_SOURCES["global"]))
    tasks = []
    for topic, description in LEGAL_TOPICS.items():
        tasks.append(
            {
                "id": f"LEGAL-{selected_region}-{topic}",
                "region": selected_region,
                "topic": topic,
                "description": description,
                "preferred_sources": sources,
                "queries": _topic_queries(topic, selected_region),
                "frequency": _topic_frequency(topic),
                "output": "legal_change_summary_risk_alert_controller_advice",
            }
        )
    return {"status": "ok", "created_at": int(time.time()), "region": selected_region, "sources": sources, "tasks": tasks, "policy": legal_monitor_policy()}


def legal_monitor_policy() -> dict[str, Any]:
    """Return rules for safe legal monitoring."""

    return {
        "not_legal_advice": True,
        "rules": [
            "Use official regulator, government, exchange or court/legislation sources when possible.",
            "Separate law, proposal, consultation, guidance and news commentary.",
            "Do not treat social media as law.",
            "If a change can affect trading, access, taxes, KYC/AML or sanctions, notify General Controller.",
            "Critical legal uncertainty should block risky actions until manual review.",
            "Always include source type and confidence level.",
        ],
        "controller_actions": ["continue", "watch", "caution", "block_action", "manual_review"],
    }


def evaluate_legal_change(change: dict[str, Any]) -> dict[str, Any]:
    """Evaluate a legal/regulatory change and advise General Controller."""

    title = str(change.get("title", "")).strip()
    source_domain = str(change.get("source_domain", "")).strip().lower()
    source_type = str(change.get("source_type", "")).strip().lower()
    topic = str(change.get("topic", "")).strip().lower()
    text = str(change.get("summary", change.get("text", ""))).lower()

    if not title:
        return {"status": "invalid", "reason": "missing_title"}

    official = _is_official_source(source_domain, source_type)
    severity = _severity_from_text(text, official)
    action = _controller_action(severity, topic, text)
    affected = _affected_bots(topic, text)
    confidence = "high" if official else "medium" if source_type in {"legal_news", "exchange_notice"} else "low"

    return {
        "status": "ok",
        "title": title,
        "topic": topic or "unknown",
        "source_domain": source_domain,
        "source_type": source_type,
        "official_source": official,
        "severity": severity,
        "confidence": confidence,
        "affected_bots": affected,
        "general_controller_advice": {
            "action": action,
            "message": _advice_message(action, severity, topic),
            "requires_manual_review": action in {"block_action", "manual_review"},
        },
    }


def legal_alert_summary(changes: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarize multiple legal changes for General Controller."""

    evaluated = [evaluate_legal_change(change) for change in changes]
    valid = [item for item in evaluated if item.get("status") == "ok"]
    highest = "info"
    for item in valid:
        if SEVERITY_ORDER[item["severity"]] > SEVERITY_ORDER[highest]:
            highest = item["severity"]
    action = "continue"
    if any(item.get("general_controller_advice", {}).get("action") == "block_action" for item in valid):
        action = "block_action"
    elif any(item.get("general_controller_advice", {}).get("action") == "manual_review" for item in valid):
        action = "manual_review"
    elif any(item.get("general_controller_advice", {}).get("action") == "caution" for item in valid):
        action = "caution"
    elif any(item.get("general_controller_advice", {}).get("action") == "watch" for item in valid):
        action = "watch"
    return {"status": "ok", "count": len(valid), "highest_severity": highest, "controller_action": action, "alerts": valid}


def _topic_queries(topic: str, region: str) -> list[str]:
    base = [f"{region} {topic} official regulatory update", f"{region} {topic} guidance consultation enforcement"]
    if topic == "crypto_regulation":
        base += [f"{region} crypto asset regulation official", f"{region} stablecoin token exchange custody regulation"]
    if topic == "aml_kyc":
        base += [f"{region} AML KYC crypto exchange sanctions guidance", f"{region} financial crime crypto assets official"]
    if topic == "tax":
        base += [f"{region} crypto tax capital gains official", f"{region} stock investment tax official"]
    return base


def _topic_frequency(topic: str) -> str:
    if topic in {"crypto_regulation", "aml_kyc", "exchange_rules"}:
        return "daily"
    if topic in {"securities_law", "tax"}:
        return "weekly"
    return "monthly"


def _is_official_source(domain: str, source_type: str) -> bool:
    if source_type in {"regulator_docs", "official", "legislation", "exchange_notice"}:
        return True
    return any(domain in sources for sources in REGULATORY_SOURCES.values())


def _severity_from_text(text: str, official: bool) -> str:
    if any(word in text for word in ("ban", "запрет", "sanction", "санкц", "criminal", "уголов", "illegal", "незакон")):
        return "critical" if official else "high"
    if any(word in text for word in ("enforcement", "штраф", "lawsuit", "иск", "penalty", "наруш")):
        return "high" if official else "caution"
    if any(word in text for word in ("new rule", "новое правило", "consultation", "guidance", "proposal", "законопроект")):
        return "caution" if official else "watch"
    if any(word in text for word in ("warning", "предупреж", "risk alert")):
        return "watch"
    return "info"


def _controller_action(severity: str, topic: str, text: str) -> str:
    if severity == "critical":
        return "block_action"
    if severity == "high":
        return "manual_review"
    if severity == "caution":
        return "caution"
    if severity == "watch":
        return "watch"
    return "continue"


def _affected_bots(topic: str, text: str) -> list[str]:
    bots = {"general_controller", "news_agent", "confidence_engine"}
    if topic in {"crypto_regulation", "aml_kyc", "exchange_rules"} or "crypto" in text:
        bots.update({"market_agent", "risk_engine", "security_guard", "paper_trading_bot"})
    if topic in {"securities_law", "tax"} or "stock" in text:
        bots.update({"portfolio_engine", "risk_engine"})
    if topic in {"data_privacy", "consumer_protection"}:
        bots.update({"security_guard", "learning_engine"})
    return sorted(bots)


def _advice_message(action: str, severity: str, topic: str) -> str:
    if action == "block_action":
        return f"Legal severity is {severity}. Block related risky actions until manual legal review. Topic: {topic}."
    if action == "manual_review":
        return f"High legal risk detected. General Controller should require manual review. Topic: {topic}."
    if action == "caution":
        return f"Regulatory change requires caution and updated bot rules. Topic: {topic}."
    if action == "watch":
        return f"Monitor this legal topic and lower confidence for affected decisions. Topic: {topic}."
    return f"No immediate legal block detected. Continue monitoring. Topic: {topic}."
