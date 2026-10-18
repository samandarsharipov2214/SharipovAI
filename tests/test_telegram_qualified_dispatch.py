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
