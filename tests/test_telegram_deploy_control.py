from __future__ import annotations

import json
import time
from pathlib import Path

import telegram_deploy_control as control


def test_owner_claim_and_deploy_request_are_restricted(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(control, "CONTROL_DIR", tmp_path)
    monkeypatch.setattr(control, "REQUEST_FILE", tmp_path / "pending.json")
    monkeypatch.setattr(control, "STATUS_FILE", tmp_path / "status.json")
    monkeypatch.setattr(control, "OWNER_FILE", tmp_path / "owner.json")
    monkeypatch.setattr(control, "CLAIM_FILE", tmp_path / "owner_claim.json")
    monkeypatch.setenv("TELEGRAM_ADMIN_USER_ID", "")
    monkeypatch.setenv("TELEGRAM_ADMIN_CHAT_ID", "")
    control._CONFIRMATIONS.clear()

    control.CLAIM_FILE.write_text(json.dumps({"code": "654321", "expires_at": int(time.time()) + 600}), encoding="utf-8")
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


def test_watcher_is_fixed_command_https_only_and_never_mounts_docker_socket():
    source = Path("scripts/sharipovai_deploy_watcher.sh").read_text(encoding="utf-8")
    assert '[[ "$action" != "deploy_main" ]]' in source
    assert 'git fetch --no-tags "${FETCH_REMOTE}" main' in source
    assert 'target_sha="$(git rev-parse FETCH_HEAD)"' in source
    assert 'git reset --hard "${target_sha}"' in source
    assert 'SHARIPOVAI_DEPLOY_WATCHER_ACTIVE=1 bash "$ROOT/scripts/deploy_web2_refresh_fix.sh"' in source
    assert "docker.sock" not in source
    assert "amnezia-awg2" not in source
