"""Russian Telegram presentation helpers for SharipovAI.

Keeps Telegram answers clear for a Russian UI: translated market labels,
source links, timestamps, and explicit explanations for decisions.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any


REGIME_LABELS = {
    "mixed": "смешанный рынок",
    "trend": "трендовый рынок",
    "panic": "паника / высокая волатильность",
    "news_shock": "новостной шок",
    "bad_execution": "плохие условия исполнения",
    "range_low_volatility": "боковик с низкой волатильностью",
    "unknown": "неизвестно",
}

REGIME_EXPLANATIONS = {
    "mixed": "нет достаточно сильного тренда и нет спокойного боковика. Сигналы противоречат друг другу, поэтому нужен консенсус ИИ и подтверждение источников.",
    "trend": "есть выраженное направление рынка, но всё равно нужна проверка риска и комиссии.",
    "panic": "рынок двигается резко; высок риск ложного входа и ликвидаций.",
    "news_shock": "новости могут резко двигать цену без технического подтверждения.",
    "bad_execution": "спред или ликвидность плохие; вход/выход может быть невыгодным.",
    "range_low_volatility": "рынок стоит в диапазоне; лучше ждать сильного сигнала.",
}

RISK_LABELS = {
    "low": "низкий",
    "medium": "средний",
    "high": "высокий",
    "unknown": "неизвестно",
}

DECISION_LABELS = {
    "BLOCK": "БЛОК: не торговать",
    "DEMO_ONLY": "только DEMO",
    "DEMO_ALLOWED": "DEMO разрешён с лимитами",
    "WATCH": "наблюдать",
    "STOP_AI": "STOP AI включён",
}

NEWS_TITLE_TRANSLATIONS = {
    "Breaking: Large BTC liquidation alert reported on social media": "Срочный сигнал: в соцсетях сообщили о крупной ликвидации по BTC",
    "Bitcoin ETF inflow increases as market volatility cools": "Приток в Bitcoin ETF растёт, пока волатильность рынка снижается",
    "Bybit announces BTC market monitoring and fee updates": "Bybit сообщил о мониторинге рынка BTC и обновлениях комиссий",
    "Security advisory reviewed for crypto wallet dependency": "Проверено предупреждение безопасности по зависимости криптокошелька",
    "Whale moved 1200 BTC from exchange wallet": "Крупный кошелёк вывел 1200 BTC с биржевого кошелька",
}


def market_regime_ru(regime: str | None) -> str:
    key = str(regime or "unknown")
    label = REGIME_LABELS.get(key, key)
    return f"{label} ({key})" if key not in {"unknown", label} else label


def market_regime_explanation(regime: str | None) -> str:
    return REGIME_EXPLANATIONS.get(str(regime or "unknown"), "режим требует дополнительной проверки.")


def risk_ru(risk: str | None) -> str:
    key = str(risk or "unknown")
    return f"{RISK_LABELS.get(key, key)} ({key})" if key not in {"unknown", RISK_LABELS.get(key, key)} else RISK_LABELS.get(key, key)


def decision_ru(decision: str | None) -> str:
    key = str(decision or "WATCH")
    return DECISION_LABELS.get(key, key)


def news_title_ru(title: str) -> str:
    clean = str(title).strip()
    if clean in NEWS_TITLE_TRANSLATIONS:
        return NEWS_TITLE_TRANSLATIONS[clean]
    lowered = clean.lower()
    replacements = [
        ("breaking", "срочно"),
        ("large btc liquidation alert", "крупная ликвидация по BTC"),
        ("reported on social media", "сообщили в соцсетях"),
        ("bitcoin etf inflow increases", "приток в Bitcoin ETF растёт"),
        ("market volatility cools", "волатильность рынка снижается"),
        ("fee updates", "обновления комиссий"),
        ("security advisory", "предупреждение безопасности"),
        ("crypto wallet", "криптокошелёк"),
    ]
    result = clean
    for src, dst in replacements:
        if src in lowered:
            result = result.replace(src, dst).replace(src.title(), dst).replace(src.capitalize(), dst)
    return result


def format_news_time(value: str | None) -> str:
    if not value:
        return "время не указано источником"
    raw = str(value).strip()
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        now = datetime.now(UTC)
        seconds = max(0, int((now - dt.astimezone(UTC)).total_seconds()))
        if seconds < 90:
            age = "только что"
        elif seconds < 3600:
            age = f"{seconds // 60} мин назад"
        elif seconds < 86400:
            age = f"{seconds // 3600} ч назад"
        else:
            age = f"{seconds // 86400} дн назад"
        return f"{dt.astimezone(UTC).strftime('%d.%m %H:%M UTC')} · {age}"
    except Exception:
        return raw


def format_news_item(item: dict[str, Any], *, index: int) -> str:
    title = news_title_ru(str(item.get("title", "Новость")))
    source = str(item.get("source_name", "Источник"))
    credibility = item.get("credibility_percent", item.get("trust_score", 0))
    published = format_news_time(str(item.get("published_at", "")))
    url = str(item.get("url", "")).strip()
    needs_confirmation = bool(item.get("needs_confirmation", False))
    action = str(item.get("ai_action", "WATCH"))
    status = "нужно подтверждение" if needs_confirmation else "подтверждение не требуется"
    link = f"\n   🔗 <a href=\"{_html_attr(url)}\">Открыть источник</a>" if url else "\n   🔗 ссылка не передана источником"
    return (
        f"{index}. <b>{_safe_html(title)}</b>\n"
        f"   Источник: <b>{_safe_html(source)}</b> · достоверность <b>{_safe_html(credibility)}%</b>\n"
        f"   Время: <b>{_safe_html(published)}</b>\n"
        f"   Статус: <b>{_safe_html(status)}</b> · AI: <b>{_safe_html(action)}</b>"
        f"{link}"
    )


def _safe_html(value: object) -> str:
    import html

    return html.escape(str(value), quote=False)


def _html_attr(value: object) -> str:
    import html

    return html.escape(str(value), quote=True)
