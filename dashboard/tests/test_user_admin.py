from __future__ import annotations

from dashboard.user_admin import (
    create_user,
    list_users,
    reset_user_password,
    set_user_active,
    set_user_role,
    verify_password,
)


def test_user_management_lifecycle() -> None:
    users_data = {"users": {}}

    created = create_user(users_data, "Pilot01", "initial-pass", role="user", must_change_password=True)
    assert created["status"] == "ok"
    assert created["username"] == "pilot01"

    users = list_users(users_data)
    assert users == [
        {
            "username": "pilot01",
            "role": "user",
            "active": True,
            "must_change_password": True,
            "created_at": users[0]["created_at"],
            "password_changed_at": 0,
            "disabled_at": 0,
        }
    ]
    assert "password_hash" not in users[0]

    disabled = set_user_active(users_data, "pilot01", False)
    assert disabled["status"] == "ok"
    assert users_data["users"]["pilot01"]["active"] is False

    enabled = set_user_active(users_data, "pilot01", True)
    assert enabled["status"] == "ok"
    assert users_data["users"]["pilot01"]["active"] is True

    promoted = set_user_role(users_data, "pilot01", "admin")
    assert promoted["status"] == "ok"
    assert users_data["users"]["pilot01"]["role"] == "admin"

    demoted = set_user_role(users_data, "pilot01", "user")
    assert demoted["status"] == "ok"
    assert users_data["users"]["pilot01"]["role"] == "user"

    reset = reset_user_password(users_data, "pilot01")
    assert reset["status"] == "ok"
    assert reset["temporary_password"].startswith("SA-")
    assert users_data["users"]["pilot01"]["must_change_password"] is True
    assert verify_password(reset["temporary_password"], users_data["users"]["pilot01"]["password_hash"]) is True


def test_user_management_returns_not_found_for_missing_user() -> None:
    users_data = {"users": {}}

    assert set_user_active(users_data, "ghost", False)["status"] == "not_found"
    assert set_user_role(users_data, "ghost", "admin")["status"] == "not_found"
    assert reset_user_password(users_data, "ghost")["status"] == "not_found"


def test_user_management_rejects_invalid_role() -> None:
    users_data = {"users": {}}
    create_user(users_data, "pilot01", "initial-pass")

    result = set_user_role(users_data, "pilot01", "owner")

    assert result["status"] == "invalid_role"
