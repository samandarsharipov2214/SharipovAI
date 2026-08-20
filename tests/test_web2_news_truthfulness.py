from pathlib import Path


PAGE = Path(__file__).resolve().parents[1] / "web2" / "app" / "page.tsx"


def test_web2_news_does_not_fabricate_fallback_events_or_impact():
    source = PAGE.read_text(encoding="utf-8")

    assert "Bitcoin обновил локальный максимум" not in source
    assert "ETF-потоки поддерживают рынок" not in source
    assert "Рост активности по BTC" not in source
    assert "i%3===0?'Высокое':'Среднее'" not in source


def test_web2_news_has_truthful_empty_state_and_only_renders_received_impact():
    source = PAGE.read_text(encoding="utf-8")

    assert "Нет подтверждённых новостей" in source
    assert "Нет подтверждённых данных API" in source
    assert "Интерфейс не подставляет демонстрационные значения." in source
    assert "x.ai_impact ?? x.impact ?? ''" in source
    assert "n.impact && <p>AI влияние: {n.impact}</p>" in source
