"""Material ingestion pipeline for SharipovAI Learning Core.

This module converts user-provided learning material into safe training assets:
- metadata
- digest
- short summary
- rules
- bot assignments
- exam questions

It intentionally does not persist full copyrighted text.
"""

from __future__ import annotations

import hashlib
import re
import time
from typing import Any

from .financial_knowledge_library import BOT_DOMAIN_MAP, DOMAINS, SOURCE_TYPES, minimum_rules_for_domains


MAX_STORED_PREVIEW_CHARS = 700
MAX_SUMMARY_SENTENCES = 5


def ingest_material(
    *,
    title: str,
    source_type: str,
    domain: str,
    content: str,
    bots: list[str] | None = None,
    rights: str = "user_provided_for_private_learning",
) -> dict[str, Any]:
    """Convert raw material into a safe learning record.

    The full content is not stored in the returned record. Only digest, preview,
    summary, rules and exam are generated.
    """

    clean_title = title.strip()
    clean_domain = domain.strip().lower()
    clean_source_type = source_type.strip().lower()
    clean_content = _normalize_text(content)

    validation = _validate_input(clean_title, clean_source_type, clean_domain, clean_content)
    if validation["status"] != "ok":
        return validation

    assigned_bots = _assign_bots(clean_domain, bots)
    summary = _summarize(clean_content)
    rules = _rules_from_material(clean_domain, clean_content)
    concepts = _extract_concepts(clean_domain, clean_content)
    exam = _exam_from_rules(clean_title, rules)

    return {
        "status": "ok",
        "material": {
            "id": _material_id(clean_title, clean_content),
            "title": clean_title,
            "source_type": clean_source_type,
            "domain": clean_domain,
            "rights": rights,
            "content_digest": hashlib.sha256(clean_content.encode("utf-8")).hexdigest(),
            "stored_preview": clean_content[:MAX_STORED_PREVIEW_CHARS],
            "full_text_stored": False,
            "created_at": int(time.time()),
            "assigned_bots": assigned_bots,
            "summary": summary,
            "concepts": concepts,
            "rules": rules,
            "exam": exam,
        },
    }


def material_to_bot_update(material: dict[str, Any], bot_name: str) -> dict[str, Any]:
    """Return a bot-specific update from one ingested material."""

    bot = bot_name.strip().lower().replace("-", "_").replace(" ", "_")
    assigned = material.get("assigned_bots", [])
    if bot not in assigned:
        return {"status": "not_assigned", "bot": bot, "material_id": material.get("id")}
    return {
        "status": "ok",
        "bot": bot,
        "material_id": material.get("id"),
        "title": material.get("title"),
        "domain": material.get("domain"),
        "summary": material.get("summary", []),
        "rules": material.get("rules", []),
        "exam": material.get("exam", []),
    }


def _validate_input(title: str, source_type: str, domain: str, content: str) -> dict[str, Any]:
    if len(title) < 3:
        return {"status": "invalid_title", "message": "title is too short"}
    if source_type not in SOURCE_TYPES:
        return {"status": "invalid_source_type", "source_type": source_type, "allowed": sorted(SOURCE_TYPES)}
    if domain not in DOMAINS:
        return {"status": "invalid_domain", "domain": domain, "allowed": sorted(DOMAINS)}
    if len(content) < 80:
        return {"status": "content_too_short", "message": "content must be at least 80 characters"}
    return {"status": "ok"}


def _assign_bots(domain: str, bots: list[str] | None) -> list[str]:
    if bots:
        return sorted({bot.strip().lower().replace("-", "_").replace(" ", "_") for bot in bots if bot.strip()})
    return sorted(bot for bot, domains in BOT_DOMAIN_MAP.items() if domain in domains)


def _summarize(content: str) -> list[str]:
    sentences = _sentences(content)
    selected = sentences[:MAX_SUMMARY_SENTENCES]
    return [sentence[:260] for sentence in selected if sentence]


def _rules_from_material(domain: str, content: str) -> list[str]:
    rules = minimum_rules_for_domains([domain])
    lowered = content.lower()
    if any(word in lowered for word in ("liquidity", "ликвид", "spread", "спред")):
        rules.append("Перед выводом проверять ликвидность, спред и возможное проскальзывание.")
    if any(word in lowered for word in ("risk", "риск", "drawdown", "просад")):
        rules.append("Если материал указывает на высокий риск, снижать уверенность и размер позиции.")
    if any(word in lowered for word in ("regulation", "регуля", "sec", "санкц", "kyc", "aml")):
        rules.append("Регуляторные факты проверять через официальный источник.")
    return _dedupe(rules)


def _extract_concepts(domain: str, content: str) -> list[str]:
    concept_keywords = {
        "ликвидность": ["liquidity", "ликвид"],
        "спред": ["spread", "спред"],
        "проскальзывание": ["slippage", "проскаль"],
        "риск": ["risk", "риск"],
        "просадка": ["drawdown", "просад"],
        "инфляция": ["inflation", "инфля"],
        "ставка": ["interest rate", "ставк"],
        "регулирование": ["regulation", "регуля", "sec"],
        "отчётность": ["earnings", "отчёт", "revenue"],
        "биржа": ["exchange", "бирж"],
    }
    lowered = content.lower()
    concepts = [name for name, keys in concept_keywords.items() if any(key in lowered for key in keys)]
    concepts.append(domain)
    return sorted(set(concepts))


def _exam_from_rules(title: str, rules: list[str]) -> list[dict[str, Any]]:
    selected = rules[:3]
    exam: list[dict[str, Any]] = []
    for index, rule in enumerate(selected, 1):
        keywords = _keywords(rule)
        exam.append(
            {
                "id": f"M-Q{index}",
                "question": f"Какое правило из материала '{title}' нужно применить?",
                "expected_keywords": keywords[:3] or ["риск"],
                "rule": rule,
            }
        )
    return exam


def _keywords(text: str) -> list[str]:
    words = re.findall(r"[A-Za-zА-Яа-яЁё0-9-]{4,}", text.lower())
    stop = {"если", "нужно", "перед", "через", "источник", "вывод", "делать", "сделку", "правило"}
    return _dedupe([word for word in words if word not in stop])


def _material_id(title: str, content: str) -> str:
    digest = hashlib.sha256(f"{title}\n{content}".encode("utf-8")).hexdigest()[:12]
    return f"MAT-{digest.upper()}"


def _normalize_text(content: str) -> str:
    return re.sub(r"\s+", " ", content.strip())


def _sentences(content: str) -> list[str]:
    parts = re.split(r"(?<=[.!?。])\s+", content)
    return [part.strip() for part in parts if part.strip()]


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result
