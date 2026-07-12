from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / 'dashboard/static/web2/index.html'
JS = ROOT / 'dashboard/static/web2/incident_center_v21.js'
CSS = ROOT / 'dashboard/static/web2/incident_center_v21.css'


def test_incident_center_files_are_connected():
    html = INDEX.read_text(encoding='utf-8')
    assert 'incident_center_v21.js?v=21' in html
    assert 'incident_center_v21.css?v=21' in html
    assert JS.is_file()
    assert CSS.is_file()


def test_incident_center_is_read_only_and_uses_existing_truth_sources():
    source = JS.read_text(encoding='utf-8')
    assert '/api/system/health' in source
    assert '/api/system/recovery-plan' in source
    assert '/api/evidence-vault/recent' in source
    assert "method:'POST'" not in source
    assert 'EXCHANGE_LIVE_TRADING_ENABLED' not in source
    assert 'TESTNET_EXECUTION_ENABLED' not in source


def test_existing_sections_remain_connected():
    html = INDEX.read_text(encoding='utf-8')
    required = [
        'operations_center_v20.js', 'news_center_v12.js', 'market_terminal_v13.js',
        'ai_center_v14.js', 'general_control_v15.js', 'portfolio_risk_v16.js',
        'learning_evidence_reports_v17.js', 'exchange_execution_settings_v18.js'
    ]
    for asset in required:
        assert asset in html
