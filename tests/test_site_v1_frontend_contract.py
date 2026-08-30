from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "dashboard" / "static" / "site-v1"


def test_forms_are_semantic_accessible_and_password_safe() -> None:
    html = (SITE / "index.html").read_text(encoding="utf-8")

    for field_id in (
        "loginEmail",
        "loginPassword",
        "registerName",
        "registerEmail",
        "registerContact",
        "registerPassword",
        "registerPasswordConfirmation",
        "registerReason",
    ):
        assert f'for="{field_id}"' in html
        assert f'id="{field_id}"' in html
    assert 'role="status"' in html
    assert 'aria-live="polite"' in html
    assert 'autocomplete="current-password"' in html
    assert html.count('autocomplete="new-password"') == 2
    assert "localStorage" not in html


def test_frontend_has_bounded_requests_and_double_submit_guards() -> None:
    source = (SITE / "site.js").read_text(encoding="utf-8")

    assert "AbortController" in source
    assert "REQUEST_TIMEOUT_MS" in source
    assert source.count('getAttribute("aria-busy") === "true"') == 2
    assert source.count("setBusy(") == 5
    assert 'JSON.stringify({ email: values.email, password: values.password })' in source
    assert "password_confirmation" in source


def test_frontend_errors_are_inline_truthful_and_not_raw_html() -> None:
    source = (SITE / "site.js").read_text(encoding="utf-8")

    for expected_state in (
        "pending_approval",
        "access_rejected",
        "already_exists",
        "Нет соединения с сервером",
        "Сервис временно недоступен",
    ):
        assert expected_state in source
    assert "textContent" in source
    assert "innerHTML" not in source
    assert "alert(" not in source
    assert "console." not in source


def test_responsive_and_accessibility_css_contracts_are_present() -> None:
    css = (SITE / "site.css").read_text(encoding="utf-8")

    assert "overflow-x: hidden" in css
    assert "min-width: 320px" in css
    assert "min-height: 44px" in css
    assert ":focus-visible" in css
    assert "prefers-reduced-motion: reduce" in css
    assert "@media (max-width: 820px)" in css
    assert "@media (max-width: 520px)" in css
