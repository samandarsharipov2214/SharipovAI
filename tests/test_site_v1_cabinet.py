from __future__ import annotations

import importlib

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import dashboard.auth_saas as auth_saas
from dashboard.global_auth_guard import install_global_auth_guard
from dashboard.site_v1_cabinet import cabinet_payload, install_site_v1_cabinet
from dashboard.site_v1_host import install_site_v1_host


class FakeLoop:
    def __init__(self, payload):
        self.payload = payload

    def snapshot(self):
        return self.payload


def _app_with_loop(payload=None, *, missing=False):
    app = FastAPI()
    if missing:
        app.state.autonomous_paper_loop = None
    else:
        app.state.autonomous_paper_loop = FakeLoop(payload)
    return app


def test_cabinet_projects_canonical_paper_without_demo_defaults() -> None:
    app = _app_with_loop(
        {
            "source_of_truth": "autonomous_paper",
            "mode": "autonomous_paper",
            "equity": 9876.5,
            "cash": 8765.4,
            "realized_pnl": -12.5,
            "unrealized_pnl": 3.25,
            "total_fees": 8.75,
            "positions": {"BTCUSDT": {"quantity": 0.01}},
            "trades": [
                {
                    "symbol": "BTCUSDT",
                    "side": "BUY",
                    "fee": 1.0,
                    "net_pnl": None,
                }
            ],
            "trade_history_count": 17,
            "last_action": "WAIT",
            "last_reason": "council authorization required",
            "worker_running": True,
            "database_backed": True,
            "peak_equity": 10000.0,
            "market_stream": {"verified": True, "age_seconds": 2},
        }
    )

    payload = cabinet_payload(app)

    assert payload["data_available"] is True
    assert payload["source_of_truth"] == "autonomous_paper"
    assert payload["equity"] == 9876.5
    assert payload["cash"] == 8765.4
    assert payload["net_pnl"] == -9.25
    assert payload["total_fees"] == 8.75
    assert payload["open_positions"] == 1
    assert payload["last_action"] == "WAIT"
    assert payload["last_reason"] == "council authorization required"
    assert payload["worker_running"] is True
    assert payload["wait"] == "WAIT"
    assert payload["drawdown_percent"] == pytest.approx(1.235)
    assert payload["error"] is None
    assert payload["realized_pnl"] == -12.5
    assert payload["unrealized_pnl"] == 3.25
    assert payload["trade_count"] == 17
    assert payload["peak_equity"] == 10000.0
    assert payload["database_backed"] is True
    assert payload["market_verified"] is True
    assert payload["market_age_seconds"] == 2
    assert payload["trades"][0]["symbol"] == "BTCUSDT"


def test_cabinet_missing_runtime_is_unavailable_without_fabricated_zeros() -> None:
    payload = cabinet_payload(_app_with_loop(missing=True))

    assert payload["data_available"] is False
    assert payload["mode"] == "UNAVAILABLE"
    assert payload["equity"] is None
    assert payload["cash"] is None
    assert payload["net_pnl"] is None
    assert payload["total_fees"] is None
    assert payload["open_positions"] is None
    assert payload["worker_running"] is None
    assert payload["drawdown_percent"] is None
    assert payload["status"] == "unavailable"
    assert payload["error"] == "autonomous_paper_loop_missing"
    assert payload["realized_pnl"] is None
    assert payload["unrealized_pnl"] is None
    assert payload["peak_equity"] is None
    assert payload["trade_count"] is None
    assert payload["database_backed"] is None
    assert payload["market_verified"] is None
    assert payload["market_age_seconds"] is None
    assert payload.get("trades") in ([], None)
    assert 0 not in (
        payload["equity"],
        payload["cash"],
        payload["net_pnl"],
        payload["total_fees"],
        payload["realized_pnl"],
        payload["unrealized_pnl"],
        payload["peak_equity"],
        payload["trade_count"],
    )


def test_cabinet_omits_drawdown_when_peak_equity_is_absent() -> None:
    app = _app_with_loop(
        {
            "mode": "autonomous_paper",
            "equity": 50.0,
            "cash": 50.0,
            "realized_pnl": 0.0,
            "unrealized_pnl": 0.0,
            "total_fees": 1.0,
            "positions": {},
            "last_action": "HOLD",
            "last_reason": "no new authorization",
            "worker_running": True,
        }
    )

    payload = cabinet_payload(app)

    assert payload["data_available"] is True
    assert payload["drawdown_percent"] is None
    assert payload["wait"] is None


def test_unauthenticated_cabinet_json_is_rejected(monkeypatch) -> None:
    monkeypatch.delenv("SHARIPOVAI_DISABLE_AUTH", raising=False)
    app = FastAPI()
    install_site_v1_cabinet(app)
    install_global_auth_guard(app)

    with TestClient(app, follow_redirects=False) as client:
        response = client.get("/api/site-v1/cabinet")

    assert response.status_code == 401
    assert "demo" not in response.text.lower()


def test_authenticated_cabinet_json_does_not_use_demo_api(monkeypatch) -> None:
    monkeypatch.delenv("SHARIPOVAI_DISABLE_AUTH", raising=False)
    app = FastAPI()
    app.state.autonomous_paper_loop = FakeLoop(
        {
            "mode": "autonomous_paper",
            "equity": 42.5,
            "cash": 40.0,
            "realized_pnl": 2.5,
            "unrealized_pnl": 0.0,
            "total_fees": 0.25,
            "positions": {},
            "last_action": "WAIT",
            "last_reason": "drawdown wait",
            "worker_running": False,
        }
    )
    install_site_v1_cabinet(app)
    install_global_auth_guard(app)
    app._session_username = lambda request: "owner"

    with TestClient(app, follow_redirects=False) as client:
        response = client.get("/api/site-v1/cabinet")

    assert response.status_code == 200
    payload = response.json()
    assert payload["equity"] == 42.5
    assert payload["wait"] == "WAIT"
    assert payload["last_reason"] == "drawdown wait"
    assert "demo" not in response.text.lower()
    assert payload["source_of_truth"] == "autonomous_paper"


def test_public_site_v1_html_and_login_redirect(monkeypatch) -> None:
    monkeypatch.delenv("SHARIPOVAI_DISABLE_AUTH", raising=False)
    app = FastAPI()
    install_site_v1_host(app)
    install_global_auth_guard(app)

    with TestClient(app, follow_redirects=False) as client:
        root = client.get("/")
        login = client.get("/login")
        register = client.get("/register")
        site_app = client.get("/app")

    assert root.status_code == 200
    assert "/static/site-v1/site.css" in root.text
    assert "access-card" in root.text
    assert "ambient" in root.text
    assert "SharipovAI Login" not in root.text
    assert login.status_code == 303
    assert login.headers["location"] == "/?mode=login"
    assert register.status_code == 303
    assert register.headers["location"] == "/?mode=register"
    assert site_app.status_code == 200
    assert "/static/site-v1/site.css" in site_app.text
    assert "access-card" in site_app.text
    assert "cabinet-card" in site_app.text
    assert "SharipovAI Login" not in site_app.text
    assert site_app.headers.get("location") is None



def test_authenticated_app_serves_site_v1_cabinet_html(monkeypatch) -> None:
    monkeypatch.delenv("SHARIPOVAI_DISABLE_AUTH", raising=False)
    app = FastAPI()
    install_site_v1_host(app)
    install_global_auth_guard(app)
    app._session_username = lambda request: "owner"

    with TestClient(app, follow_redirects=False) as client:
        response = client.get("/app")

    assert response.status_code == 200
    assert "cabinet-card" in response.text
    assert "Рабочий кабинет" in response.text
    assert "SharipovAI Login" not in response.text
    assert "Обзор" in response.text
    assert "Портфель" in response.text
    assert "Сделки" in response.text
    assert "/static/web2/" not in response.text


def test_login_accepts_legacy_owner_username(monkeypatch) -> None:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    from dashboard.models_saas import Base

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(auth_saas, "SessionLocal", sessions)
    monkeypatch.setenv("AUTH_SECRET", "site-v1-test-auth-secret-not-production")
    app_mod = importlib.import_module("dashboard.app")
    monkeypatch.setattr(app_mod, "_valid_credentials", lambda username, password: username == "owner" and password == "owner-secret-pass")
    monkeypatch.setattr(
        app_mod,
        "_load_users",
        lambda: {"owner": {"role": "admin", "active": True}},
    )
    monkeypatch.setattr(app_mod, "_is_production", lambda: False)

    app = FastAPI()
    auth_saas.install_saas_auth_api(app)
    client = TestClient(app, follow_redirects=False)
    response = client.post(
        "/api/auth/login",
        headers={"host": "testserver", "origin": "http://testserver"},
        json={"email": "owner", "password": "owner-secret-pass"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["authenticated"] is True
    assert body["user"]["display_name"] == "owner"
    set_cookie = response.headers.get("set-cookie", "")
    assert "sharipovai_session=" in set_cookie
    assert "httponly" in set_cookie.lower()
    me = client.get("/api/auth/me")
    assert me.status_code == 200
    assert me.json()["authenticated"] is True
    assert me.json()["user"]["email"] == "owner"
