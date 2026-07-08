"""Financial knowledge library for SharipovAI bots.

The library stores source metadata, learning objectives, allowed usage,
and bot assignments. It does not store full copyrighted books/articles.
"""

from __future__ import annotations

from typing import Any


DOMAINS = {
    "crypto": "Криптовалюты, блокчейн, токены, биржи, кошельки, ончейн-метрики.",
    "stocks": "Акции, отчётность компаний, мультипликаторы, дивиденды, индексы.",
    "exchanges": "Биржи, стакан, ликвидность, комиссии, типы ордеров, исполнение.",
    "trading": "Покупка, продажа, риск, стоп-лосс, тейк-профит, позиция, стратегия.",
    "financial_institutions": "Банки, брокеры, фонды, маркет-мейкеры, клиринг, депозитарии.",
    "macro": "Ставки, инфляция, центральные банки, ликвидность, экономические циклы.",
    "risk": "Просадка, плечо, ликвидация, корреляция, VAR, риск-лимиты.",
    "regulation": "Регуляторы, отчётность, санкции, KYC/AML, защита инвестора.",
}


SOURCE_TYPES = {
    "official_document",
    "exchange_documentation",
    "book",
    "research_paper",
    "article",
    "course_note",
    "market_report",
    "user_uploaded_file",
}


BOT_DOMAIN_MAP = {
    "market_agent": ["crypto", "stocks", "exchanges", "trading", "macro"],
    "news_agent": ["crypto", "stocks", "macro", "regulation"],
    "risk_engine": ["risk", "trading", "exchanges", "financial_institutions"],
    "portfolio_engine": ["stocks", "crypto", "risk", "financial_institutions"],
    "paper_trading_bot": ["trading", "exchanges", "risk"],
    "confidence_engine": ["risk", "macro", "regulation"],
    "consensus_engine": ["crypto", "stocks", "risk", "macro"],
    "stress_bot": ["risk", "macro", "financial_institutions"],
    "learning_engine": list(DOMAINS.keys()),
    "security_guard": ["exchanges", "regulation", "risk"],
    "general_controller": list(DOMAINS.keys()),
}


def knowledge_manifest() -> dict[str, Any]:
    """Return the financial knowledge manifest."""

    return {
        "status": "ok",
        "mode": "source_registry_and_learning_objectives",
        "copyright_policy": "Store metadata, notes, rules and short summaries only. Do not store full copyrighted books or paid articles unless the user has rights and uploads them for private processing.",
        "domains": DOMAINS,
        "source_types": sorted(SOURCE_TYPES),
        "bot_domain_map": BOT_DOMAIN_MAP,
        "core_concepts": core_concepts(),
        "source_registry": source_registry(),
        "bot_curriculum": {bot: bot_curriculum(bot) for bot in sorted(BOT_DOMAIN_MAP)},
    }


def source_registry() -> list[dict[str, Any]]:
    """Return curated source categories and learning targets.

    These are not full texts. They are a map of what the system should learn from.
    """

    return [
        {
            "id": "SRC-CRYPTO-001",
            "domain": "crypto",
            "source_type": "official_document",
            "title": "Bitcoin whitepaper and protocol basics",
            "learn": ["proof_of_work", "scarcity", "block_confirmation", "transaction_finality"],
            "bots": ["market_agent", "risk_engine", "learning_engine"],
        },
        {
            "id": "SRC-CRYPTO-002",
            "domain": "crypto",
            "source_type": "exchange_documentation",
            "title": "Crypto exchange order types and risk controls",
            "learn": ["market_order", "limit_order", "stop_order", "liquidation", "funding_rate"],
            "bots": ["paper_trading_bot", "risk_engine", "security_guard"],
        },
        {
            "id": "SRC-STOCKS-001",
            "domain": "stocks",
            "source_type": "course_note",
            "title": "Equity basics and company financial statements",
            "learn": ["revenue", "net_income", "cash_flow", "valuation", "earnings"],
            "bots": ["market_agent", "portfolio_engine", "confidence_engine"],
        },
        {
            "id": "SRC-EXCHANGE-001",
            "domain": "exchanges",
            "source_type": "exchange_documentation",
            "title": "Order book, spread, liquidity and execution quality",
            "learn": ["bid_ask_spread", "slippage", "liquidity", "depth", "maker_taker"],
            "bots": ["market_agent", "paper_trading_bot", "risk_engine"],
        },
        {
            "id": "SRC-TRADING-001",
            "domain": "trading",
            "source_type": "book",
            "title": "Trading risk management and position sizing",
            "learn": ["position_size", "stop_loss", "take_profit", "risk_reward", "trade_journal"],
            "bots": ["risk_engine", "paper_trading_bot", "learning_engine"],
        },
        {
            "id": "SRC-INSTITUTIONS-001",
            "domain": "financial_institutions",
            "source_type": "book",
            "title": "How financial institutions, brokers, clearing and custody work",
            "learn": ["broker", "clearing", "custody", "market_maker", "settlement"],
            "bots": ["portfolio_engine", "risk_engine", "general_controller"],
        },
        {
            "id": "SRC-MACRO-001",
            "domain": "macro",
            "source_type": "official_document",
            "title": "Central bank rates, inflation and liquidity reports",
            "learn": ["interest_rate", "inflation", "liquidity", "risk_on", "risk_off"],
            "bots": ["news_agent", "market_agent", "stress_bot"],
        },
        {
            "id": "SRC-REG-001",
            "domain": "regulation",
            "source_type": "official_document",
            "title": "Securities and crypto regulation basics",
            "learn": ["disclosure", "investor_protection", "market_abuse", "kyc", "aml"],
            "bots": ["news_agent", "security_guard", "confidence_engine"],
        },
    ]


def core_concepts() -> list[dict[str, str]]:
    """Core concepts every finance-aware bot should understand."""

    return [
        {"id": "C-001", "concept": "Ликвидность", "meaning": "Насколько легко купить или продать актив без сильного движения цены."},
        {"id": "C-002", "concept": "Спред", "meaning": "Разница между лучшей ценой покупки и продажи."},
        {"id": "C-003", "concept": "Проскальзывание", "meaning": "Разница между ожидаемой и фактической ценой исполнения."},
        {"id": "C-004", "concept": "Плечо", "meaning": "Увеличение позиции за счёт заёмных средств, увеличивает прибыль и риск."},
        {"id": "C-005", "concept": "Ликвидация", "meaning": "Принудительное закрытие позиции при нехватке маржи."},
        {"id": "C-006", "concept": "Риск-менеджмент", "meaning": "Ограничение потерь, размера позиции и общей просадки."},
        {"id": "C-007", "concept": "Фундаментальный анализ", "meaning": "Оценка бизнеса, финансов, экономики и ценности актива."},
        {"id": "C-008", "concept": "Технический анализ", "meaning": "Анализ цены, объёма, тренда и структуры рынка."},
        {"id": "C-009", "concept": "Маркет-мейкер", "meaning": "Участник рынка, который обеспечивает ликвидность котировками покупки и продажи."},
        {"id": "C-010", "concept": "Клиринг", "meaning": "Процесс расчётов и подтверждения обязательств после сделки."},
    ]


def bot_curriculum(bot_name: str) -> dict[str, Any]:
    """Return finance curriculum for one bot."""

    bot = bot_name.strip().lower().replace("-", "_").replace(" ", "_")
    domains = BOT_DOMAIN_MAP.get(bot)
    if not domains:
        return {"status": "not_found", "bot": bot_name}

    sources = [source for source in source_registry() if source["domain"] in domains or bot in source.get("bots", [])]
    concepts = _concepts_for_domains(domains)
    return {
        "status": "ok",
        "bot": bot,
        "domains": domains,
        "concepts": concepts,
        "sources": sources,
        "minimum_rules": minimum_rules_for_domains(domains),
    }


def minimum_rules_for_domains(domains: list[str]) -> list[str]:
    """Return minimum rules required for the selected domains."""

    rules = [
        "Не делать вывод без источника или объяснения.",
        "Всегда отделять факт от предположения.",
        "Не рекомендовать реальную сделку без риск-проверки.",
    ]
    if "crypto" in domains:
        rules.append("Для крипты проверять ликвидность, волатильность, биржу и риск ликвидации.")
    if "stocks" in domains:
        rules.append("Для акций учитывать отчётность, сектор, новости и рыночный режим.")
    if "exchanges" in domains:
        rules.append("Перед сделкой учитывать стакан, спред, комиссии и проскальзывание.")
    if "risk" in domains:
        rules.append("При высоком риске снижать размер позиции или блокировать сделку.")
    if "regulation" in domains:
        rules.append("Регуляторные новости требуют официального источника и перепроверки.")
    return rules


def _concepts_for_domains(domains: list[str]) -> list[str]:
    domain_concepts = {
        "crypto": ["ликвидность", "волатильность", "кошелёк", "он-чейн", "ликвидация"],
        "stocks": ["выручка", "прибыль", "денежный поток", "дивиденды", "оценка"],
        "exchanges": ["стакан", "спред", "комиссия", "проскальзывание", "исполнение"],
        "trading": ["покупка", "продажа", "стоп-лосс", "тейк-профит", "позиция"],
        "financial_institutions": ["банк", "брокер", "клиринг", "депозитарий", "маркет-мейкер"],
        "macro": ["ставка", "инфляция", "ликвидность", "рецессия", "risk-on/risk-off"],
        "risk": ["просадка", "плечо", "лимит", "корреляция", "капитал"],
        "regulation": ["регулятор", "раскрытие", "KYC", "AML", "санкции"],
    }
    result: list[str] = []
    for domain in domains:
        result.extend(domain_concepts.get(domain, []))
    return sorted(set(result))
