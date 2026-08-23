from __future__ import annotations

import dashboard.telegram_webhook_api as telegram_api
import telegram_deploy_control as deploy_control


def _clear_owner_env(monkeypatch):
    for name in (
        "TELEGRAM_OWNER_ID",
        "TELEGRAM_OWNER_CHAT_ID",
        "TELEGRAM_ADMIN_USER_ID",
        "TELEGRAM_ADMIN_CHAT_ID",
    ):
        monkeypatch.delenv(name, raising=False)


def test_partial_canonical_chat_config_fails_closed_before_legacy(monkeypatch):
    _clear_owner_env(monkeypatch)
    monkeypatch.setenv("TELEGRAM_OWNER_CHAT_ID", "-202")
    monkeypatch.setenv("TELEGRAM_ADMIN_USER_ID", "101")

    assert deploy_control.expected_bootstrap_owner() is None


def test_canonical_user_only_config_remains_supported(monkeypatch):
    _clear_owner_env(monkeypatch)
    monkeypatch.setenv("TELEGRAM_OWNER_ID", "101")

    assert deploy_control.expected_bootstrap_owner() == (101, None)


def test_webhook_owner_ids_require_native_integers_and_allow_signed_chat():
    valid = {"message": {"from": {"id": 101}, "chat": {"id": -202}, "text": "/deploy"}}
    assert telegram_api._telegram_update_user_id(valid) == 101
    assert telegram_api._telegram_update_chat_id(valid) == -202

    for bad_actor in ("101", 101.9, True, 0, -1):
        update = {"message": {"from": {"id": bad_actor}, "chat": {"id": -202}, "text": "/deploy"}}
        assert telegram_api._telegram_update_user_id(update) is None

    for bad_chat in ("-202", -202.9, True, 0):
        update = {"message": {"from": {"id": 101}, "chat": {"id": bad_chat}, "text": "/deploy"}}
        assert telegram_api._telegram_update_chat_id(update) is None


def test_bootstrap_claim_bypass_closes_after_persisted_owner(monkeypatch):
    monkeypatch.setattr(telegram_api, "persisted_owner", lambda: (101, -202))
    monkeypatch.setattr(telegram_api, "expected_bootstrap_owner", lambda: (101, -202))

    update = {
        "message": {
            "from": {"id": 101},
            "chat": {"id": -202},
            "text": "/claim_owner 654321",
        }
    }
    assert telegram_api._owner_bootstrap_claim_update(update) is False


def test_bootstrap_claim_accepts_only_exact_owner_and_nonempty_code(monkeypatch):
    monkeypatch.setattr(telegram_api, "persisted_owner", lambda: None)
    monkeypatch.setattr(telegram_api, "expected_bootstrap_owner", lambda: (101, -202))

    valid = {"message": {"from": {"id": 101}, "chat": {"id": -202}, "text": "/claim_owner 654321"}}
    wrong_actor = {"message": {"from": {"id": 999}, "chat": {"id": -202}, "text": "/claim_owner 654321"}}
    wrong_chat = {"message": {"from": {"id": 101}, "chat": {"id": -999}, "text": "/claim_owner 654321"}}
    no_code = {"message": {"from": {"id": 101}, "chat": {"id": -202}, "text": "/claim_owner"}}

    assert telegram_api._owner_bootstrap_claim_update(valid) is True
    assert telegram_api._owner_bootstrap_claim_update(wrong_actor) is False
    assert telegram_api._owner_bootstrap_claim_update(wrong_chat) is False
    assert telegram_api._owner_bootstrap_claim_update(no_code) is False


def test_bot_qualified_claim_requires_current_bot_and_is_normalized_for_handler(monkeypatch):
    monkeypatch.setattr(telegram_api, "persisted_owner", lambda: None)
    monkeypatch.setattr(telegram_api, "expected_bootstrap_owner", lambda: (101, -202))
    monkeypatch.setattr(telegram_api, "_current_bot_username", lambda: "sharipovai_bot")

    current = {
        "message": {
            "from": {"id": 101},
            "chat": {"id": -202},
            "text": "/claim_owner@SharipovAI_Bot 654321",
        }
    }
    foreign = {
        "message": {
            "from": {"id": 101},
            "chat": {"id": -202},
            "text": "/claim_owner@OtherBot 654321",
        }
    }

    assert telegram_api._owner_bootstrap_claim_update(current) is True
    assert telegram_api._owner_bootstrap_claim_update(foreign) is False

    processed = []
    monkeypatch.setattr(telegram_api, "handle_message", lambda message: processed.append(message))
    telegram_api._process_update_safely(current)

    assert processed == [
        {
            "from": {"id": 101},
            "chat": {"id": -202},
            "text": "/claim_owner 654321",
        }
    ]
