import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from dashboard import telegram_webhook_api as api
import telegram_system_adapter as adapter

@pytest.mark.parametrize('command',['/start','/status','/whoami','/news','/agent explain risk'])
def test_own_qualified_commands_reach_handler_after_existing_approval(monkeypatch,command):
 app=FastAPI();seen=[];claims=[]
 monkeypatch.setattr(api,'_webhook_secret',lambda:'fixture')
 monkeypatch.setattr(api,'_current_bot_username',lambda:'our_bot')
 monkeypatch.setattr(api,'claim_telegram_update',lambda ident:claims.append(ident) or True)
 monkeypatch.setattr(api,'_approved_telegram_user_id',lambda update:101)
 monkeypatch.setattr(api,'handle_message',lambda message:seen.append(message))
 api.install_telegram_webhook_api(app)
 token,*rest=command.split(maxsplit=1);qualified=token+'@Our_Bot'+(' '+rest[0] if rest else '')
 response=TestClient(app).post('/telegram/webhook',headers={'X-Telegram-Bot-Api-Secret-Token':'fixture'},json={'update_id':1,'message':{'text':qualified,'chat':{'id':101},'from':{'id':101}}})
 assert response.status_code==200 and claims==[1]
 assert seen[0]['text']==command and seen[0]['from']['id']==101

@pytest.mark.parametrize('username',['our_bot',None])
def test_foreign_or_unknown_username_is_not_dispatched(monkeypatch,username):
 app=FastAPI();monkeypatch.setattr(api,'_webhook_secret',lambda:'fixture');monkeypatch.setattr(api,'_current_bot_username',lambda:username)
 monkeypatch.setattr(api,'claim_telegram_update',lambda _:pytest.fail('foreign command must not claim an update'))
 api.install_telegram_webhook_api(app)
 response=TestClient(app).post('/telegram/webhook',headers={'X-Telegram-Bot-Api-Secret-Token':'fixture'},json={'update_id':1,'message':{'text':'/deploy@other_bot'}})
 assert response.json()['ignored'] is True

def test_qualified_command_does_not_bypass_user_approval(monkeypatch):
 app=FastAPI();monkeypatch.setattr(api,'_webhook_secret',lambda:'fixture');monkeypatch.setattr(api,'_current_bot_username',lambda:'our_bot');monkeypatch.setattr(api,'claim_telegram_update',lambda _:True)
 monkeypatch.setattr(api,'_approved_telegram_user_id',lambda _:None);monkeypatch.setattr(api,'_owner_deploy_control_update',lambda _:False);monkeypatch.setattr(api,'_owner_bootstrap_claim_update',lambda _:False)
 monkeypatch.setattr(api,'handle_message',lambda _:pytest.fail('unapproved user dispatched'))
 api.install_telegram_webhook_api(app)
 response=TestClient(app).post('/telegram/webhook',headers={'X-Telegram-Bot-Api-Secret-Token':'fixture'},json={'update_id':1,'message':{'text':'/status@our_bot'}})
 assert response.json()['reason']=='telegram_user_not_approved'

def test_news_uses_existing_evidence_renderer_not_llm(monkeypatch):
 import telegram_bot
 sent=[];monkeypatch.setattr(telegram_bot,'news_text',lambda:'verified news fixture')
 monkeypatch.setattr(adapter,'main_keyboard',lambda *args:{})
 monkeypatch.setattr(adapter,'send_message',lambda chat,text,kb:sent.append(text))
 monkeypatch.setattr(adapter,'_reply',lambda _:pytest.fail('news unexpectedly sent to LLM'))
 adapter.handle_message({'chat':{'id':1},'from':{'id':1},'text':'/news'})
 assert sent==['verified news fixture']


@pytest.mark.parametrize("failure", [{"ok": False}, {"ok": True, "result": {}}, RuntimeError("offline")])
def test_bot_identity_recovers_after_bounded_failure(monkeypatch, failure):
    monkeypatch.delenv("TELEGRAM_BOT_USERNAME", raising=False)
    monkeypatch.setattr(api, "_BOT_USERNAME_CACHE", None)
    monkeypatch.setattr(api, "_BOT_USERNAME_RESOLVED", False)
    monkeypatch.setattr(api, "_BOT_USERNAME_RETRY_AT", 0.0)
    clock = [100.0]
    calls = []
    monkeypatch.setattr(api.time, "monotonic", lambda: clock[0])
    def lookup(method):
        calls.append(method)
        if len(calls) == 1:
            if isinstance(failure, Exception):
                raise failure
            return failure
        return {"ok": True, "result": {"username": "Our_Bot"}}
    monkeypatch.setattr(api, "_telegram", lookup)
    assert api._normalize_command_text("/status@Our_Bot") is None
    clock[0] = 159.0
    assert api._normalize_command_text("/status@Our_Bot") is None
    assert len(calls) == 1
    clock[0] = 161.0
    assert api._normalize_command_text("/status@Our_Bot") == "/status"
    assert api._normalize_command_text("/status@Other_Bot") is None
    assert len(calls) == 2


def test_webhook_identity_lookup_runs_outside_event_loop(monkeypatch):
    import asyncio
    import threading
    import httpx
    app = FastAPI()
    monkeypatch.setattr(api, "_webhook_secret", lambda: "fixture")
    monkeypatch.setattr(api, "claim_telegram_update", lambda _: True)
    monkeypatch.setattr(api, "_approved_telegram_user_id", lambda _: 101)
    monkeypatch.setattr(api, "handle_message", lambda _: None)
    async def exercise():
        loop_thread = threading.get_ident()
        def normalize(text):
            assert threading.get_ident() != loop_thread
            return "/status"
        monkeypatch.setattr(api, "_normalize_command_text", normalize)
        api.install_telegram_webhook_api(app)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/telegram/webhook", headers={"X-Telegram-Bot-Api-Secret-Token": "fixture"}, json={"update_id": 1, "message": {"text": "/status@Our_Bot"}})
        assert response.status_code == 200
    asyncio.run(exercise())


def test_concurrent_cold_start_commands_share_identity_lookup(monkeypatch):
    import threading
    from concurrent.futures import ThreadPoolExecutor
    monkeypatch.delenv("TELEGRAM_BOT_USERNAME", raising=False)
    monkeypatch.setattr(api, "_BOT_USERNAME_CACHE", None)
    monkeypatch.setattr(api, "_BOT_USERNAME_RESOLVED", False)
    monkeypatch.setattr(api, "_BOT_USERNAME_RETRY_AT", 0.0)
    entered, release, waiting = threading.Event(), threading.Event(), threading.Event()
    lock = threading.Lock()
    class ObservedLock:
        def acquire(self, **kwargs):
            if lock.locked():
                waiting.set()
            return lock.acquire(**kwargs)
        def release(self):
            lock.release()
    monkeypatch.setattr(api, "_BOT_USERNAME_LOCK", ObservedLock())
    calls = []
    def lookup(method):
        calls.append(method)
        entered.set()
        assert release.wait(3)
        return {"ok": True, "result": {"username": "Our_Bot"}}
    monkeypatch.setattr(api, "_telegram", lookup)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(api._normalize_command_text, "/status@Our_Bot")
        try:
            assert entered.wait(3)
            second = pool.submit(api._normalize_command_text, "/news@Our_Bot")
            assert waiting.wait(3)
        finally:
            release.set()
        assert first.result(timeout=3) == "/status"
        assert second.result(timeout=3) == "/news"
    assert calls == ["getMe"]
