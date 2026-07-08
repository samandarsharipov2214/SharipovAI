"""HTML helpers for role-aware menu visibility."""

from __future__ import annotations

import re


SECURITY_LINK_RE = re.compile(r'<a\s+href="/security\?lang=ru">Кибер-безопасность</a>')


def hide_security_link_for_non_admin(html: str, *, admin: bool) -> str:
    """Remove the security-center menu link for non-admin users."""

    if admin:
        return html
    return SECURITY_LINK_RE.sub("", html)
