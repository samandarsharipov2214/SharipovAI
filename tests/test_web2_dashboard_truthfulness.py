from pathlib import Path


PAGE = Path(__file__).resolve().parents[1] / "web2" / "app" / "page.tsx"


def test_web2_dashboard_does_not_fabricate_trading_or_performance_values():
    source = PAGE.read_text(encoding="utf-8")

    forbidden = (
        "24356.22",
        "18640.42",
        "+314.22 USDT",
        "+2 156.87 USDT",
        "BUY BTC",
        "92%",
        "118 432.45",
        "89.7%",
        "+47.2%",
        "2.31",
        "0.012 BTC",
        "12.5 SOL",
    )
    for value in forbidden:
        assert value not in source


def test_web2_dashboard_uses_api_values_or_explicit_unknown_state():
    source = PAGE.read_text(encoding="utf-8")

    assert "finiteNumber(account?.total_equity)" in source
    assert "finiteNumber(account?.total_available_balance)" in source
    assert "Нет подтверждённых данных API" in source
    assert "Демонстрационные торговые значения не показываются" in source
    assert "Показываются только подтверждённые данные API" in source


def test_web2_bots_do_not_invent_default_agent_statuses():
    source = PAGE.read_text(encoding="utf-8")

    assert "General Controller','Market AI','News AI" not in source
    assert "Статус не указан" in source
    assert "row.last_action" in source
