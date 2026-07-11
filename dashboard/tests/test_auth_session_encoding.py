from __future__ import annotations

import base64

from dashboard.auth_storage_aliases import (
    _decode_legacy_session,
    _unquote_cookie_value,
)


def test_legacy_session_parser_handles_dots_inside_binary_hmac() -> None:
    payload = b"samandar2212:1783802000:fixed-nonce"
    signature = b".first-dot." + bytes(range(21))
    assert len(signature) == 32

    token = base64.urlsafe_b64encode(payload + b"." + signature).decode()

    assert _decode_legacy_session(token) == (payload, signature)


def test_cookie_transport_quotes_are_removed_once() -> None:
    token = "YWJjZA=="

    assert _unquote_cookie_value(f'"{token}"') == token
    assert _unquote_cookie_value(f"'{token}'") == token
    assert _unquote_cookie_value(token) == token
