from __future__ import annotations

import json

import dashboard.telegram_webhook_api as telegram_api
import telegram_deploy_control as deploy_control


def _owner_file(tmp_path, monkeypatch, *, user_id: int = 101, chat_id: int = 202):
    owner_file = tmp_path / "deployment_control" / "owner.json"
    owner_file.parent.mkdir(parents=True)
    owner_file.write_text(
        json.dumps({"user_id": user_id, "chat_id": chat_id, "claimed_at": 1}),
        encoding="utf-8",
    )
    monkeypatch.setattr(deploy_control, "OWNER_FILE", owner_file)
    return owner_file


def test_owner_deploy_gate_requires_exact_persisted_actor_and_chat(tmp_path, monkeypatch):
    _owner_file(tmp_path, monkeypatch)

    exact_owner = {
        "message": {
            "from": {"id": 101},
            "chat": {"id": 202},
            "text": "/deploy",
        }
    }
    foreign_actor_same_chat = {
        "message": {
            "from": {"id": 999},
            "chat": {"id": 202},
            "text": "/deploy",
        }
    }
    owner_wrong_chat = {
        "message": {
            "from": {"id": 101},
            "chat": {"id": 303},
            "text": "/deploy",
        }
    }

    assert telegram_api._owner_deploy_control_update(exact_owner) is True
    assert telegram_api._owner_deploy_control_update(foreign_actor_same_chat) is False
    assert telegram_api._owner_deploy_control_update(owner_wrong_chat) is False


def test_owner_deploy_gate_fails_closed_for_missing_or_malformed_owner(tmp_path, monkeypatch):
    owner_file = tmp_path / "deployment_control" / "owner.json"
    monkeypatch.setattr(deploy_control, "OWNER_FILE", owner_file)

    deploy = {
        "message": {
            "from": {"id": 101},
            "chat": {"id": 202},
            "text": "/deploy",
        }
    }

    assert telegram_api._owner_deploy_control_update(deploy) is False

    owner_file.parent.mkdir(parents=True)
    owner_file.write_text("not-json", encoding="utf-8")
    assert telegram_api._owner_deploy_control_update(deploy) is False
