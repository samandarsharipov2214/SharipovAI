from __future__ import annotations

from dashboard.menu_visibility import hide_security_link_for_non_admin


def test_admin_keeps_security_link() -> None:
    html = '<nav><a href="/">Обзор</a><a href="/security?lang=ru">Кибер-безопасность</a><a href="/logout">Выйти</a></nav>'

    result = hide_security_link_for_non_admin(html, admin=True)

    assert 'href="/security?lang=ru"' in result
    assert "Кибер-безопасность" in result


def test_non_admin_loses_security_link() -> None:
    html = '<nav><a href="/">Обзор</a><a href="/security?lang=ru">Кибер-безопасность</a><a href="/logout">Выйти</a></nav>'

    result = hide_security_link_for_non_admin(html, admin=False)

    assert 'href="/security?lang=ru"' not in result
    assert "Кибер-безопасность" not in result
    assert 'href="/logout"' in result
