from __future__ import annotations

from dashboard.roles import clean_username, is_admin, resolve_role


def test_clean_username_normalizes_input() -> None:
    assert clean_username("  Samandar2212  ") == "samandar2212"


def test_admin_role_comes_from_admin_username(monkeypatch) -> None:
    monkeypatch.setenv("ADMIN_USERNAME", "Samandar2212")

    role = resolve_role("samandar2212", {"users": {}})

    assert role == "admin"
    assert is_admin("Samandar2212", {"users": {}}) is True


def test_user_role_comes_from_users_file(monkeypatch) -> None:
    monkeypatch.setenv("ADMIN_USERNAME", "Samandar2212")
    users_data = {"users": {"pilot01": {"role": "user"}, "security01": {"role": "admin"}}}

    assert resolve_role("pilot01", users_data) == "user"
    assert is_admin("pilot01", users_data) is False
    assert resolve_role("security01", users_data) == "admin"
    assert is_admin("security01", users_data) is True


def test_unknown_user_has_no_role(monkeypatch) -> None:
    monkeypatch.setenv("ADMIN_USERNAME", "Samandar2212")

    assert resolve_role("ghost", {"users": {}}) is None
    assert is_admin("ghost", {"users": {}}) is False
