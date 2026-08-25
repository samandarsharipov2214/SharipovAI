from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
import dashboard.site_v1_api as api
from dashboard.models_saas import AccessRequest, Base, User

def test_v1_registration_is_pending_and_password_is_not_in_request(monkeypatch):
    engine=create_engine("sqlite://",connect_args={"check_same_thread":False},poolclass=StaticPool)
    Base.metadata.create_all(engine); sessions=sessionmaker(bind=engine)
    monkeypatch.setattr(api,"SessionLocal",sessions); app=FastAPI(); api.install_site_v1_api(app); client=TestClient(app)
    payload={"name":"Ada","email":"ada@example.test","contact":"@ada","password":"correct-horse-battery","password_confirmation":"correct-horse-battery","reason":"research"}
    response=client.post("/api/site-v1/access-requests",json=payload,headers={"host":"testserver","origin":"http://testserver"})
    assert response.status_code==200 and response.json()["status"]=="pending_approval"
    with sessions() as db:
        user=db.scalar(select(User).where(User.email==payload["email"])); request=db.scalar(select(AccessRequest).where(AccessRequest.user_id==user.id))
        assert user.is_active is False and payload["password"] not in user.password_hash
        assert request.contact==payload["contact"] and not hasattr(request,"password")

def test_v1_rejects_mismatch_and_cross_origin(monkeypatch):
    app=FastAPI(); api.install_site_v1_api(app); client=TestClient(app)
    payload={"name":"Ada","email":"ada@example.test","contact":"@ada","password":"correct-horse-battery","password_confirmation":"another-long-password"}
    response=client.post("/api/site-v1/access-requests",json=payload,headers={"host":"testserver","origin":"http://testserver"})
    assert response.status_code==422 and response.json()["detail"]["status"]=="password_mismatch"
