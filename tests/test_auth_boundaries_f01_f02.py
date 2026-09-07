"""F01/F02 auth boundary regressions: login throttle parity + bot mailbox ownership."""
from __future__ import annotations

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

import dashboard.bot_communication_api as bot_api
import dashboard.evidence_recorder_middleware as evidence
import learning.bot_communication_app as standalone_bot_api
from dashboard import create_app


class DummyRunner:
    def run(self):
        raise RuntimeError("not used")


@pytest.fixture(autouse=True)
def _reset_login_throttle() -> None:
    evidence._LOGIN_FAILURES.clear()
    yield
    evidence._LOGIN_FAILURES.clear()


def test_json_login_shares_form_login_ip_throttle(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setenv("SHARIPOVAI_DISABLE_AUTH", "1")
    monkeypatch.setenv("LOGIN_MAX_FAILURES", "3")
    monkeypatch.setenv("AUTH_USERS_FILE", str(tmp_path / "users.json"))
    monkeypatch.setenv("POLICY_JOURNAL_FILE", str(tmp_path / "policy.json"))
    # Re-bind the module constant after env override.
    monkeypatch.setattr(evidence, "LOGIN_MAX_FAILURES", 3)

    client = TestClient(create_app(runner_factory=DummyRunner))
    payload = {"email": "attacker@example.test", "password": "wrong-password-long"}

    for _ in range(3):
        response = client.post("/api/auth/login", json=payload)
        assert response.status_code == 401

    blocked_json = client.post("/api/auth/login", json=payload)
    assert blocked_json.status_code == 429
    assert blocked_json.json()["status"] == "rate_limited"

    # Same IP bucket must also protect form POST /login (do not weaken form protection).
    blocked_form = client.post("/login", data={"username": "attacker", "password": "wrong"})
    assert blocked_form.status_code == 429
    assert blocked_form.json()["status"] == "rate_limited"


def test_form_login_failures_also_throttle_json_login(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setenv("SHARIPOVAI_DISABLE_AUTH", "1")
    monkeypatch.setenv("LOGIN_MAX_FAILURES", "3")
    monkeypatch.setenv("AUTH_USERS_FILE", str(tmp_path / "users.json"))
    monkeypatch.setenv("POLICY_JOURNAL_FILE", str(tmp_path / "policy.json"))
    monkeypatch.setattr(evidence, "LOGIN_MAX_FAILURES", 3)

    client = TestClient(create_app(runner_factory=DummyRunner))
    for _ in range(3):
        response = client.post("/login", data={"username": "nobody", "password": "bad"})
        assert response.status_code == 401

    blocked = client.post(
        "/api/auth/login",
        json={"username": "nobody", "password": "bad-password-long"},
    )
    assert blocked.status_code == 429
    assert blocked.json()["status"] == "rate_limited"


class _FakeNetwork:
    def inbox(self, *_args, **_kwargs):
        return [{"message_id": "MSG-1", "payload": {"secret": "tenant-a"}}]

    def outbox(self, *_args, **_kwargs):
        return [{"message_id": "MSG-2", "payload": {"secret": "tenant-a"}}]

    def thread(self, thread_id: str):
        return {"status": "ok", "thread_id": thread_id, "messages": [{"message_id": "MSG-3"}]}

    def health(self):
        return {"status": "ok", "responsibilities": {}}

    def communication_matrix(self):
        return {"status": "ok"}


def _mailbox_client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    network = _FakeNetwork()
    app = FastAPI()
    monkeypatch.setattr(bot_api, "BotCommunicationNetwork", lambda _path=None: network)
    bot_api.install_bot_communication_api(app)
    return TestClient(app)


def test_bot_mailbox_reads_require_owner_when_auth_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SHARIPOVAI_DISABLE_AUTH", raising=False)
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("RENDER", "1")

    def deny(_request):
        raise HTTPException(status_code=403, detail={"status": "forbidden"})

    monkeypatch.setattr(bot_api, "require_admin", deny)
    client = _mailbox_client(monkeypatch)

    for path in (
        "/api/bot-network/inbox/learning_engine",
        "/api/bot-network/outbox/general_controller",
        "/api/bot-network/threads/THR-1",
    ):
        response = client.get(path)
        assert response.status_code == 403, path
        assert response.json()["detail"]["status"] == "forbidden"


def test_bot_mailbox_reads_allow_authenticated_owner(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SHARIPOVAI_DISABLE_AUTH", raising=False)
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("RENDER", "1")
    monkeypatch.setattr(bot_api, "require_admin", lambda _request: "owner-admin")
    client = _mailbox_client(monkeypatch)

    inbox = client.get("/api/bot-network/inbox/learning_engine")
    assert inbox.status_code == 200
    assert inbox.json()["messages"][0]["payload"]["secret"] == "tenant-a"

    outbox = client.get("/api/bot-network/outbox/general_controller")
    assert outbox.status_code == 200
    assert len(outbox.json()["messages"]) == 1

    thread = client.get("/api/bot-network/threads/THR-1")
    assert thread.status_code == 200
    assert thread.json()["thread_id"] == "THR-1"


def test_standalone_bot_mailbox_reads_fail_closed_without_ownership_proof(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    network = _FakeNetwork()
    monkeypatch.setattr(standalone_bot_api, "network", lambda: network)
    client = TestClient(standalone_bot_api.app)

    for path in (
        "/api/bot-network/inbox/risk_engine",
        "/api/bot-network/outbox/general_controller",
        "/api/bot-network/threads/THR-1",
    ):
        response = client.get(path)
        assert response.status_code == 401, path
        assert response.json()["detail"]["status"] == "unauthorized"
        assert "tenant-a" not in response.text
