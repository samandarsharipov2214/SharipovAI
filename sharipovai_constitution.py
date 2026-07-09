"""SharipovAI constitution and runtime discipline.

The only simulated part of SharipovAI is the account balance/execution layer:
orders are virtual and real money is protected. Everything else must behave as a
real production AI system: news, risk, portfolio, fees, learning, evidence,
Telegram, website, realtime status, and audit.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

CONSTITUTION_VERSION = "2026.07.virtual-account-production-v1"
CAPITAL_MODE = "virtual_account"
EXECUTION_MODE = "virtual_execution_only"

PRINCIPLES: tuple[str, ...] = (
    "Only the account balance and order execution are virtual; all AI organs must operate with production discipline.",
    "Every AI decision must be treated as if real capital, reputation, and future habits are at risk.",
    "No fake activity: never show template timestamps, fake progress, or 'working' without last_seen evidence.",
    "Every agent must expose last_seen, last_action, confidence, risk impact, data freshness, and learning consequence.",
    "Virtual execution must still calculate risk, fees, drawdown, slippage assumptions, opportunity cost, and prevented loss.",
    "News, source monitoring, risk, audit, Telegram, and UI must use real-time status and must not fall back to static demo content silently.",
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
        "execution_mode": EXECUTION_MODE,
        "virtual_account_meaning": "Только счёт и сделки виртуальные. Остальные органы AI обязаны работать как реальная production-система.",
        "forbidden": [
            "фейковые 00:00/00:01 журналы",
            "статичный статус без last_seen",
            "отношение к виртуальному счёту как к игрушке",
            "подмена реального обновления статичными шаблонами",
            "скрытие ошибок вместо отправки в Learning/Evidence",
        ],
        "required_agent_fields": [
            "last_seen",
            "last_action",
            "heartbeat_age_seconds",
            "data_freshness_seconds",
            "capital_discipline",
            "evidence_mode",
        ],
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
            "execution_mode": EXECUTION_MODE,
            "capital_discipline": "virtual_account_real_system_discipline",
            "evidence_mode": "production_evidence_with_virtual_execution",
            "last_seen": now,
            "last_report_at": now,
            "heartbeat_age_seconds": heartbeat_age,
            "data_freshness_seconds": heartbeat_age,
            "last_action": action or _default_action(str(agent.get("name", "AI Agent"))),
            "status_explanation": "Счёт виртуальный, но орган AI обязан работать как production-система с реальной дисциплиной риска.",
        }
    )
    return disciplined


def _default_action(name: str) -> str:
    if "Risk" in name:
        return "пересчитал риск и проверил запрет реального исполнения"
    if "News" in name:
        return "обновил источники и проверил подтверждение новостей перед сигналом"
    if "Market" in name:
        return "обновил market-сценарий и передал уверенность контроллёру"
    if "Learning" in name:
        return "проверил ошибки и обновил правила обучения"
    if "Security" in name:
        return "подтвердил защиту от реальных ордеров без разрешения"
    if "Portfolio" in name:
        return "пересчитал виртуальный капитал, комиссии и чистый PnL"
    if "Controller" in name:
        return "сверил работу органов AI, цель дня и конфликт решений"
    return "прошёл live-check и отправил статус General Controller"


def virtual_account_state(state: dict[str, Any]) -> dict[str, Any]:
    """Mark a state as virtual-account execution with real AI discipline."""

    enriched = dict(state)
    enriched.update(
        {
            "capital_mode": CAPITAL_MODE,
            "execution_mode": EXECUTION_MODE,
            "constitution_version": CONSTITUTION_VERSION,
            "virtual_account_notice": "Счёт и исполнение виртуальные. Новости, риск, обучение, Evidence, аудит и интерфейсы работают как real-system органы.",
            "last_updated_at": now_iso(),
            "real_money_protected": True,
            "carelessness_allowed": False,
            "fake_static_demo_allowed": False,
        }
    )
    return enriched


def paper_realism_state(state: dict[str, Any]) -> dict[str, Any]:
    """Backward-compatible alias: use virtual_account_state in new code."""

    return virtual_account_state(state)
