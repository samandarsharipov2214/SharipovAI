from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
AUTH_GUARD = ROOT / "dashboard" / "global_auth_guard.py"
WEB2_HOST = ROOT / "dashboard" / "web2_host.py"


def test_site_v1_root_is_public_but_login_and_api_contracts_remain_explicit() -> None:
    source = AUTH_GUARD.read_text(encoding="utf-8")
    public_block = source.split("_PUBLIC_EXACT = {", 1)[1].split("}", 1)[0]
    assert '"/",' in public_block
    assert '"/login"' in public_block
    assert '"/api/health"' in public_block


def test_anonymous_ui_requests_redirect_to_login() -> None:
    source = AUTH_GUARD.read_text(encoding="utf-8")
    assert 'if path.startswith("/api/")' in source
    assert "RedirectResponse(" in source
    assert 'url=f"/login?next={quote(safe_next' in source
    assert "status_code=303" in source
    assert '"status": "unauthorized"' in source


def test_web2_no_longer_owns_the_public_root() -> None:
    source = WEB2_HOST.read_text(encoding="utf-8")
    assert '"/market", "/news"' in source
    assert "FileResponse(WEB2_INDEX" in source
    assert "no-store, no-cache, must-revalidate" in source
