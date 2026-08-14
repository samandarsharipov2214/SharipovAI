from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VERIFY = ROOT / "scripts" / "verify_web2_refresh_contracts.sh"
AUTH_GUARD = ROOT / "dashboard" / "global_auth_guard.py"


def test_public_verifier_preserves_root_auth_gate() -> None:
    source = VERIFY.read_text(encoding="utf-8")

    assert 'public_root_status="$(' in source
    assert 'if [[ "$public_root_status" != "303"' in source
    assert '"/login?next=/"' in source
    assert "PUBLIC_ROOT_AUTH_GATE_FAILED" in source
    assert "PUBLIC_ROOT_AUTH_GATE_OK" in source
    assert "--location" not in source
    assert " -L " not in source


def test_public_verifier_checks_static_web2_shell_not_private_root() -> None:
    source = VERIFY.read_text(encoding="utf-8")

    assert '"$PUBLIC_URL/static/web2/index.html"' in source
    assert 'public_static_status="$(' in source
    assert 'if [[ "$public_static_status" != "200" ]]' in source
    assert "PUBLIC_WEB2_STATIC_HTTP_STATUS_FAILED" in source
    assert "PUBLIC_WEB2_STATIC_HTTP_STATUS_OK" in source
    assert "PUBLIC_WEB2_ASSET_FAMILY_FAILED" in source
    assert "PUBLIC_WEB2_ASSET_FAMILIES_OK" in source
    assert '"$PUBLIC_URL/health"' in source
    assert '"$PUBLIC_URL/api/health"' in source


def test_verifier_does_not_require_anonymous_root_to_be_web2() -> None:
    source = VERIFY.read_text(encoding="utf-8")

    assert "PUBLIC_WEB2_HTTP_STATUS_OK" not in source
    assert "PUBLIC_WEB2_CACHE_CONTROL_OK" not in source
    assert "PUBLIC_WEB2_CACHE_CONTROL_FAILED" not in source
    assert '--output "$public_index_tmp"' in source
    assert '"$PUBLIC_URL/static/web2/index.html"' in source


def test_auth_guard_remains_fail_closed_for_root() -> None:
    source = AUTH_GUARD.read_text(encoding="utf-8")
    public_block = source.split("_PUBLIC_EXACT = {", 1)[1].split("}", 1)[0]

    assert '"/",' not in public_block
    assert '"/dashboard",' not in public_block
    assert '"/login"' in public_block
    assert 'if path.startswith("/api/")' in source
    assert "status_code=303" in source
    assert 'url=f"/login?next={quote(safe_next' in source


def test_telegram_verifier_uses_canonical_health_error_freshness() -> None:
    source = VERIFY.read_text(encoding="utf-8")

    assert 'health.get("verdict") == "working"' in source
    assert 'not health.get("last_error_is_current")' in source
    assert 'not info.get("last_error_message")' not in source
    assert 'health.get("stale_webhook_error_ignored")' in source
    assert "TELEGRAM_HISTORICAL_WEBHOOK_ERROR_IGNORED" in source
    assert 'info.get("url") == f"{expected}/telegram/webhook"' in source
    assert 'menu.get("type") == "web_app"' in source
    assert "menu_url == expected" in source


def test_telegram_verifier_failure_is_diagnostic_without_raw_error_message() -> None:
    source = VERIFY.read_text(encoding="utf-8")

    assert '"last_error_date": health.get("last_error_date")' in source
    assert '"last_error_is_current": bool(health.get("last_error_is_current"))' in source
    assert '"stale_webhook_error_ignored": bool(health.get("stale_webhook_error_ignored"))' in source
    assert 'raise AssertionError(f"Telegram webhook/menu verification failed: {last_evidence}")' in source
    assert '"last_error_message":' not in source
