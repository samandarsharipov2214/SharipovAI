from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / 'dashboard' / 'static' / 'web2' / 'index.html'
GUARD = ROOT / 'dashboard' / 'static' / 'web2' / 'runtime_render_guard_v24.js'


def test_page_ownership_script_order():
    html = INDEX.read_text(encoding='utf-8')
    assert html.index('navigation_coordinator_v23.js') < html.index('runtime_render_guard_v24.js') < html.index('web2.js?v=20')


def test_page_ownership_markers_present():
    source = GUARD.read_text(encoding='utf-8')
    assert "page === 'overview'" in source
    assert "page === 'market'" in source
    assert 'legacyOverviewMarkers' in source
    assert 'isLegacyOverwrite(value)' in source
