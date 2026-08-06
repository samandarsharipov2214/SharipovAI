"""Semantic contracts for the canonical SharipovAI Web2 Mini App shell."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WEB2 = ROOT / "dashboard" / "static" / "web2"
INDEX = WEB2 / "index.html"


def test_canonical_mini_app_has_complete_russian_navigation() -> None:
    text = INDEX.read_text(encoding="utf-8")
    expected = {
        "overview": "Обзор",
        "market": "Рынок",
        "decision": "Решение ИИ",
        "portfolio": "Портфель",
        "trades": "Сделки",
        "bots": "Центр ИИ",
        "chat": "ИИ-чат",
        "news": "Новости",
        "risk": "Центр рисков",
        "bybit": "Bybit",
        "learning": "Центр обучения",
        "control": "Главное управление",
        "evidence": "Хранилище доказательств",
        "virtual": "Виртуальный счёт",
        "campaigns": "Кампании",
        "reports": "Отчёты",
        "settings": "Настройки",
    }
    for page, label in expected.items():
        assert f'data-page="{page}"' in text
        assert label in text
    assert 'data-lang="ru"' in text
    assert 'data-lang="en"' in text
    assert 'data-lang="uz"' in text


def test_canonical_pages_and_campaign_monitor_are_current_owners() -> None:
    index = INDEX.read_text(encoding="utf-8")
    canonical = (WEB2 / "canonical_pages_v45.js").read_text(encoding="utf-8")
    campaigns = (WEB2 / "campaign_operations_v36.js").read_text(encoding="utf-8")

    assert "canonical_pages_v45.js?v=45" in index
    assert "campaign_operations_v36.js?v=36" in index
    for retired in (
        "exchange_execution_settings_v18.js",
        "portfolio_risk_v16.js",
        "general_control_v15.js",
        "learning_evidence_reports_v17.js",
    ):
        assert retired not in index
    for marker in (
        "CouncilAuthorizedPaperLoop",
        "Комиссии",
        "Цена выхода",
        "real_orders_blocked",
        "execution_kill_switch",
        "risk_engine.canonical_service",
    ):
        assert marker in canonical
    assert "/v5/order/create" not in canonical
    for marker in (
        "10–25 USDT",
        "20 matched fills",
        "orphan_execution_count",
        "duplicate_order_count",
        "unresolved_order_count",
        "actual_fee_total",
        "final_report",
    ):
        assert marker in campaigns


def test_current_shell_switches_canonical_renderer_owners() -> None:
    coordinator = (WEB2 / "navigation_coordinator_v44.js").read_text(encoding="utf-8")
    guard = (WEB2 / "runtime_render_guard_v24.js").read_text(encoding="utf-8")

    assert "PAGE_OWNERS" in coordinator
    assert "activePage" in coordinator
    assert "history.replaceState" in coordinator
    assert "aria-current" in coordinator
    assert "overview_runtime_v44.js" in coordinator
    assert "canonical_pages_v45.js" in coordinator
    assert "ai_center_v44.js" in coordinator
    assert "system_status_v44.js" in coordinator
    assert "sections_v10.js" in coordinator
    assert "market_terminal_v13.js" in coordinator
    assert "Object.defineProperty(content, 'innerHTML'" in guard
    assert "runtimeRenderGuard" in guard
    assert "descriptor.set.call" in guard


def test_current_mini_app_loads_canonical_apis_without_raw_orders() -> None:
    sources = "\n".join(
        (WEB2 / filename).read_text(encoding="utf-8")
        for filename in (
            "overview_runtime_v44.js",
            "canonical_pages_v45.js",
            "ai_center_v44.js",
            "news_center_v12.js",
            "campaign_operations_v36.js",
        )
    )
    for route in (
        "/api/system/runtime-truth",
        "/api/autonomous-paper/events",
        "/api/social-news",
        "/api/campaigns/operations",
    ):
        assert route in sources
    assert "/api/virtual-account/state" not in sources
    assert "/api/ai-bots" not in sources
    assert "/api/run" not in sources
    assert "/v5/order/create" not in sources
    assert "Math.random" not in sources
