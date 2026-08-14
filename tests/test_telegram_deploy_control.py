from __future__ import annotations

import json
import time
from pathlib import Path

import telegram_deploy_control as control


def _configure_control(tmp_path: Path, monkeypatch, *, owner_id: str = "111", owner_chat_id: str = "") -> None:
    monkeypatch.setattr(control, "CONTROL_DIR", tmp_path)
    monkeypatch.setattr(control, "REQUEST_FILE", tmp_path / "pending.json")
    monkeypatch.setattr(control, "STATUS_FILE", tmp_path / "status.json")
    monkeypatch.setattr(control, "OWNER_FILE", tmp_path / "owner.json")
    monkeypatch.setattr(control, "CLAIM_FILE", tmp_path / "owner_claim.json")
    monkeypatch.setenv("TELEGRAM_ADMIN_USER_ID", "")
    monkeypatch.setenv("TELEGRAM_ADMIN_CHAT_ID", "")
    monkeypatch.setenv("TELEGRAM_OWNER_ID", owner_id)
    monkeypatch.setenv("TELEGRAM_OWNER_CHAT_ID", owner_chat_id)
    control._CONFIRMATIONS.clear()


def _write_claim(code: str = "654321", *, expires_at: int | None = None) -> None:
    control.CLAIM_FILE.write_text(
        json.dumps({"code": code, "expires_at": expires_at or int(time.time()) + 600}),
        encoding="utf-8",
    )


def test_owner_claim_and_deploy_request_are_restricted(tmp_path: Path, monkeypatch):
    _configure_control(tmp_path, monkeypatch)

    _write_claim()
    text, _ = control.claim_owner(111, 111, "bad")
    assert "Неверный" in text
    text, keyboard = control.claim_owner(111, 111, "654321")
    assert "назначен владельцем" in text
    assert keyboard["inline_keyboard"]
    assert control.is_admin(111, 111)
    assert not control.is_admin(222, 222)

    text, keyboard = control.prepare_confirmation(222, 222)
    assert "только владельцу" in text
    assert keyboard["inline_keyboard"] == []

    text, keyboard = control.prepare_confirmation(111, 111)
    token = keyboard["inline_keyboard"][0][0]["callback_data"].split(":", 2)[2]
    text, _ = control.confirm_deployment(111, 111, token)
    assert "поставлено в очередь" in text
    payload = json.loads(control.REQUEST_FILE.read_text(encoding="utf-8"))
    assert payload["action"] == "deploy_main"
    assert payload["actor_id"] == 111


def test_claim_rejects_wrong_user_without_creating_owner(tmp_path: Path, monkeypatch):
    _configure_control(tmp_path, monkeypatch, owner_id="111")
    _write_claim()

    text, _ = control.claim_owner(222, 222, "654321")

    assert "не является" in text
    assert not control.OWNER_FILE.exists()
    assert control.CLAIM_FILE.exists()


def test_claim_rejects_wrong_chat_when_canonical_chat_is_configured(tmp_path: Path, monkeypatch):
    _configure_control(tmp_path, monkeypatch, owner_id="111", owner_chat_id="333")
    _write_claim()

    text, _ = control.claim_owner(111, 222, "654321")

    assert "не является" in text
    assert not control.OWNER_FILE.exists()


def test_claim_fails_closed_without_canonical_owner(tmp_path: Path, monkeypatch):
    _configure_control(tmp_path, monkeypatch, owner_id="")
    _write_claim()

    text, _ = control.claim_owner(111, 111, "654321")

    assert "не настроен" in text
    assert not control.OWNER_FILE.exists()


def test_claim_rejects_expired_and_reused_codes(tmp_path: Path, monkeypatch):
    _configure_control(tmp_path, monkeypatch)
    _write_claim(expires_at=int(time.time()) - 1)
    text, _ = control.claim_owner(111, 111, "654321")
    assert "истёк" in text
    assert not control.OWNER_FILE.exists()

    _write_claim()
    text, _ = control.claim_owner(111, 111, "654321")
    assert "назначен владельцем" in text
    assert not control.CLAIM_FILE.exists()
    text, _ = control.claim_owner(111, 111, "654321")
    assert "уже настроен" in text


def test_claimed_owner_cannot_be_replaced(tmp_path: Path, monkeypatch):
    _configure_control(tmp_path, monkeypatch)
    _write_claim()
    control.claim_owner(111, 111, "654321")
    _write_claim(code="999999")

    text, _ = control.claim_owner(222, 222, "999999")

    assert "уже настроен" in text
    owner = json.loads(control.OWNER_FILE.read_text(encoding="utf-8"))
    assert owner["user_id"] == 111


def test_stale_running_deploy_is_terminalized_and_matching_pending_removed(tmp_path: Path, monkeypatch):
    _configure_control(tmp_path, monkeypatch)
    monkeypatch.setattr(control.time, "time", lambda: 10_000)
    control.REQUEST_FILE.write_text(json.dumps({"request_id": "request-a"}), encoding="utf-8")
    control.STATUS_FILE.write_text(
        json.dumps({"state": "running", "request_id": "request-a", "updated_at": 9_000}),
        encoding="utf-8",
    )

    status = control.read_status()

    assert status["state"] == "timeout"
    assert status["stage"] == "stale_status"
    assert not control.REQUEST_FILE.exists()


def test_stale_status_does_not_remove_a_newer_request(tmp_path: Path, monkeypatch):
    _configure_control(tmp_path, monkeypatch)
    monkeypatch.setattr(control.time, "time", lambda: 10_000)
    control.REQUEST_FILE.write_text(json.dumps({"request_id": "request-new"}), encoding="utf-8")
    control.STATUS_FILE.write_text(
        json.dumps({"state": "running", "request_id": "request-old", "updated_at": 9_000}),
        encoding="utf-8",
    )

    assert control.read_status()["state"] == "timeout"
    assert json.loads(control.REQUEST_FILE.read_text(encoding="utf-8"))["request_id"] == "request-new"


def test_watcher_is_fixed_command_https_only_and_never_mounts_docker_socket():
    source = Path("scripts/sharipovai_deploy_watcher.sh").read_text(encoding="utf-8")
    assert '[[ "$action" != "deploy_main" ]]' in source
    assert 'git fetch --no-tags "${FETCH_REMOTE}" main' in source
    assert 'target_sha="$(git rev-parse FETCH_HEAD)"' in source
    assert 'git reset --hard "${target_sha}"' in source
    assert 'env SHARIPOVAI_DEPLOY_WATCHER_ACTIVE=1' in source
    assert 'timeout --signal=TERM --kill-after=' in source
    assert "docker.sock" not in source
    assert "amnezia-awg2" not in source
