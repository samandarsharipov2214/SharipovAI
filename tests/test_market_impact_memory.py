from memory.market_impact_memory import MarketImpactMemory
from memory.unified_memory import DEFAULT_RETENTION_DAYS, IMPACT_NEWS_RETENTION_DAYS, UnifiedMemory


def test_material_news_is_kept_for_one_year(tmp_path) -> None:
    memory = UnifiedMemory(tmp_path / "memory.json")
    engine = MarketImpactMemory(memory, material_threshold_percent=1.0)
    impact = engine.record(
        title="ETF approval boosts Bitcoin demand",
        symbol="BTCUSDT",
        price_before=100.0,
        price_after=103.0,
        source="news_ai",
        tags=["ETF", "approval"],
        occurred_at=1_700_000_000,
    )
    stored = memory.get("market_news_impact", impact.news_id)
    assert impact.material is True
    assert impact.retention_days == IMPACT_NEWS_RETENTION_DAYS
    assert stored is not None
    assert stored.retention_days == IMPACT_NEWS_RETENTION_DAYS


def test_non_material_news_uses_six_month_retention(tmp_path) -> None:
    memory = UnifiedMemory(tmp_path / "memory.json")
    engine = MarketImpactMemory(memory, material_threshold_percent=1.0)
    impact = engine.record(
        title="Routine market update",
        symbol="BTCUSDT",
        price_before=100.0,
        price_after=100.2,
        source="news_ai",
        occurred_at=1_700_000_000,
    )
    assert impact.material is False
    assert impact.retention_days == DEFAULT_RETENTION_DAYS


def test_third_similar_news_can_use_two_previous_reactions(tmp_path) -> None:
    memory = UnifiedMemory(tmp_path / "memory.json")
    engine = MarketImpactMemory(memory, material_threshold_percent=1.0)
    engine.record(
        title="Bitcoin ETF approval increases institutional demand",
        symbol="BTCUSDT",
        price_before=100.0,
        price_after=104.0,
        source="news_ai",
        tags=["bitcoin", "etf", "approval"],
        news_id="first",
        occurred_at=1_700_000_000,
    )
    engine.record(
        title="New Bitcoin ETF approved for institutional investors",
        symbol="BTCUSDT",
        price_before=110.0,
        price_after=114.4,
        source="news_ai",
        tags=["bitcoin", "etf", "approval"],
        news_id="second",
        occurred_at=1_700_100_000,
    )
    pattern = engine.similar_pattern(
        title="Another Bitcoin ETF receives approval",
        symbol="BTCUSDT",
        tags=["bitcoin", "etf", "approval"],
        minimum_similarity=0.2,
    )
    assert pattern["material_match_count"] == 2
    assert pattern["expected_direction"] == "up"
    assert pattern["usable_for_decision"] is True
    assert pattern["pattern_confidence"] == 1.0


def test_expired_regular_memory_is_removed(tmp_path) -> None:
    memory = UnifiedMemory(tmp_path / "memory.json")
    memory.put("analysis", "old", {"result": "x"}, source="test", retention_days=1, now=100)
    assert memory.cleanup_expired(now=100 + 86401) == 1
    assert memory.get("analysis", "old") is None
