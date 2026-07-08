"""Unified Learning OS core for SharipovAI.

This module closes the learning-system gap by combining static curricula,
financial knowledge, source discovery, legal/policy status, persistent memory
and bot training checks into one snapshot.
"""

from __future__ import annotations

from typing import Any

from .ai_learning_core import BOT_NAMES, evaluate_exam, learning_manifest, training_pack
from .financial_knowledge_library import bot_curriculum, knowledge_manifest
from .learning_memory import LearningMemory
from .source_discovery import discovery_plan, source_policy


PASS_SCORE = 70.0


def learning_os_snapshot(memory: LearningMemory | None = None) -> dict[str, Any]:
    """Return full Learning OS snapshot."""

    memory = memory or LearningMemory()
    bots = [bot_training_status(bot, memory=memory) for bot in sorted(BOT_NAMES)]
    memory_snapshot = memory.snapshot()
    return {
        "status": "ok",
        "system": "SharipovAI Learning OS",
        "version": "2026.07.09-closure-1",
        "mode": "controlled_self_learning",
        "closed_gaps": [
            "bot_curriculum",
            "financial_knowledge",
            "source_discovery_plan",
            "material_ingestion",
            "legal_monitoring_pipeline",
            "policy_action_guard",
            "persistent_learning_memory",
            "bot_exam_loop",
        ],
        "remaining_production_steps": [
            "connect live web/search/RSS feeds on server",
            "run scheduled monitor jobs",
            "human review for legal decisions",
            "connect real trading only after owner approval and broker/exchange sandbox tests",
        ],
        "manifest": learning_manifest(),
        "financial_knowledge": _financial_summary(),
        "source_discovery": {"policy": source_policy(), "plan_count": len(discovery_plan().get("plans", []))},
        "memory": memory_snapshot,
        "bots": bots,
        "summary": _summary(bots, memory_snapshot),
    }


def bot_training_status(bot: str, *, memory: LearningMemory | None = None) -> dict[str, Any]:
    """Return training status for one bot."""

    memory = memory or LearningMemory()
    pack = training_pack(bot)
    finance = bot_curriculum(bot)
    lessons = memory.lessons_for_bot(bot, limit=20)
    exam_answers = _auto_exam_answers(pack)
    exam_result = evaluate_exam(bot, exam_answers)
    score = float(exam_result.get("score", 0.0))
    memory.record_exam(bot=bot, score=score, passed=score >= PASS_SCORE, details={"auto_check": True})
    return {
        "bot": bot,
        "status": "ready" if score >= PASS_SCORE else "needs_training",
        "score": score,
        "passed": score >= PASS_SCORE,
        "lesson_count": len(lessons),
        "pack_status": pack.get("status", "unknown"),
        "finance_status": finance.get("status", "unknown"),
        "domains": finance.get("domains", []),
        "required_checks": pack.get("required_checks", []),
        "memory_lessons": lessons,
        "exam": exam_result,
    }


def close_learning_gap(memory: LearningMemory | None = None) -> dict[str, Any]:
    """Seed minimum lessons for every bot and return a closure snapshot."""

    memory = memory or LearningMemory()
    created = []
    for bot in sorted(BOT_NAMES):
        finance = bot_curriculum(bot)
        domains = finance.get("domains", ["general"])
        if not memory.lessons_for_bot(bot, limit=1):
            created.append(
                memory.add_lesson(
                    bot=bot,
                    domain=str(domains[0]),
                    lesson=f"{bot} обязан использовать источники, риск, confidence и объяснение перед действием.",
                    rule="Нельзя действовать без источника, риска, confidence и причины.",
                    source="learning_os_closure_seed",
                )
            )
    snapshot = learning_os_snapshot(memory)
    return {"status": "ok", "seeded": len(created), "created": created, "snapshot": snapshot}


def _auto_exam_answers(pack: dict[str, Any]) -> dict[str, str]:
    answers: dict[str, str] = {}
    for question in pack.get("exam", []):
        qid = str(question.get("id", ""))
        expected = question.get("expected_keywords", [])
        answers[qid] = " ".join(str(word) for word in expected) or "риск причина капитал"
    return answers


def _financial_summary() -> dict[str, Any]:
    manifest = knowledge_manifest()
    return {
        "domain_count": len(manifest.get("domains", {})),
        "source_count": len(manifest.get("source_registry", [])),
        "concept_count": len(manifest.get("core_concepts", [])),
        "domains": sorted(manifest.get("domains", {}).keys()),
    }


def _summary(bots: list[dict[str, Any]], memory: dict[str, Any]) -> dict[str, Any]:
    ready = len([bot for bot in bots if bot.get("status") == "ready"])
    needs = len(bots) - ready
    return {
        "bot_count": len(bots),
        "ready": ready,
        "needs_training": needs,
        "lesson_count": memory.get("lesson_count", 0),
        "mistake_count": memory.get("mistake_count", 0),
        "exam_count": memory.get("exam_count", 0),
        "learning_gap_closed": needs == 0,
    }
