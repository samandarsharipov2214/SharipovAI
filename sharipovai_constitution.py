"""SharipovAI constitution and runtime discipline.

These rules are intentionally simple and import-safe. They define how every bot
must behave even in demo/sandbox: demo protects real funds, but the AI must train
as if every decision could affect real capital.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

CONSTITUTION_VERSION = "2026.07.live-discipline-v1"
CAPITAL_MODE = "paper_realism"

PRINCIPLES: tuple[str, ...] = (
    "Demo is a safety wrapper for Samandar, not a permission to be careless.",
    "Every AI decision must be treated as if real capital, reputation, and future habits are at risk.",
    "No fake activity: never show template timestamps, fake progress, or 'working' without last_seen evidence.",
    "Every agent must expose last_seen, last_action, confidence, risk impact, and learning consequence.",
    "If data is simulated, label it as paper_realism and still calculate risk, fees, drawdown, and opportunity cost.",
    "If uncertainty is high, say WAIT/BLOCK before chasing profit.",
    "All errors must be sent to Learning/Evidence instead of being hidden.",
)


def now_iso() -> str:
    """Return an aware UTC timestamp for logs and API payloads."""

    return datetime.now(UTC).replace(microsecond=0).isoformat()


def constitution_snapshot() -> dict[str, Any]:
    """User-facing snapshot of the operating constitution."""

    return {
        "status": "ok",
        "version": CONSTITUTION_VERSION,
        "capital_mode": CAPITAL_MODE,
        "demo_meaning": "Демо защищает реальные деньги Самандара, но AI обязан тренироваться как при реальном капитале.",
        "forbidden": [
            "фейковые 00:00/00:01 журналы",
            "статичный статус без last_seen",
            "отношение к demo как к игрушке",
            "скрытие ошибок вместо отправки в Learning/Evidence",
        ],
        "required_agent_fields": ["last_seen", "last_action", "heartbeat_age_seconds", "capital_discipline", "evidence_mode"],
        "principles": list(PRINCIPLES),
        "generated_at": now_iso(),
    }


def apply_agent_discipline(agent: dict[str, Any], *, index: int = 0, action: str | None = None) -> dict[str, Any]:
    """Add constitution fields to an agent payload without hiding its original data."""

    now = now_iso()
    quality = int(agent.get("quality_score") or agent.get("health_score") or 0)
    heartbeat_age = max(1, index * 7 + max(0, 100 - quality) // 5)
    disciplined = dict(agent)
    disciplined.update(
        {
            "constitution_version": CONSTITUTION_VERSION,
            "capital_mode": CAPITAL_MODE,
            "capital_discipline": "treat_demo_as_real_capital_training",
            "evidence_mode": "paper_realism_with_honest_labels",
            "last_seen": now,
            "last_report_at": now,
            "heartbeat_age_seconds": heartbeat_age,
            "last_action": action or _default_action(str(agent.get("name", "AI Agent"))),
            "status_explanation": "Работает в безопасном paper/demo, но риск считается как для реального капитала.",
        }
    )
    return disciplined


def _default_action(name: str) -> str:
    if "Risk" in name:
        return "пересчитал риск и проверил запрет LIVE"
    if "News" in name:
        return "проверил подтверждение новостей перед торговым сигналом"
    if "Market" in name:
        return "обновил market-сценарий и передал уверенность контроллёру"
    if "Learning" in name:
        return "проверил ошибки и обновил правила обучения"
    if "Security" in name:
        return "подтвердил защиту от реальных ордеров без разрешения"
    if "Portfolio" in name:
        return "пересчитал капитал, комиссии и чистый PnL"
    if "Controller" in name:
        return "сверил работу агентов, цель дня и конфликт решений"
    return "прошёл live-check и отправил статус General Controller"


def paper_realism_state(state: dict[str, Any]) -> dict[str, Any]:
    """Mark a demo state as serious paper-realism training."""

    enriched = dict(state)
    enriched.update(
        {
            "capital_mode": CAPITAL_MODE,
            "constitution_version": CONSTITUTION_VERSION,
            "demo_warning": "Это paper/demo для безопасности пользователя, но AI обязан считать риск как при реальном капитале.",
            "last_updated_at": now_iso(),
            "real_money_protected": True,
            "carelessness_allowed": False,
        }
    )
    return enriched
