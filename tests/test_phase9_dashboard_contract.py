from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_phase9_api_and_live_assets_are_installed():
    init = (ROOT/'dashboard/__init__.py').read_text(encoding='utf-8')
    index = (ROOT/'dashboard/static/web2/index.html').read_text(encoding='utf-8')
    api = (ROOT/'dashboard/phase9_campaign_api.py').read_text(encoding='utf-8')
    assert 'install_phase9_campaign_api(app)' in init
    assert 'campaign_scaling_v41.js' in index
    assert '/api/campaigns/phase9/scaling-plan' in api
    assert 'require_admin(request)' in api
