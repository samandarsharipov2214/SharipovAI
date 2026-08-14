from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from dashboard.global_auth_guard import install_global_auth_guard


ROOT = Path(__file__).resolve().parents[1]
VERIFY = ROOT / "scripts" / "verify_web2_refresh_contracts.sh"


def _unauthenticated_app() -> FastAPI:
    app = FastAPI()
    # Avoid importing the production app just to resolve a session in this
    # isolated middleware contract test.
    app._session_username = lambda _request: None  # type: ignore[attr-defined]

    @app.get("/")
    async def root() -> dict[str, bool]:
        return {"web2": True}

    @app.get("/dashboard")
    async def dashboard() -> dict[str, bool]:
        return {"web2": True}

    @app.get("/private-page")
    async def private_page() -> dict[str, bool]:
        return {"private": True}

    @app.get("/api/private-contract")
    async def private_api() -> dict[str, bool]:
        return {"private": True}

    install_global_auth_guard(app)
    return app


def test_public_web2_shell_does_not_weaken_api_auth(monkeypatch) -> None:
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.delenv("SHARIPOVAI_DISABLE_AUTH", raising=False)

    with TestClient(_unauthenticated_app()) as client:
        for path in ("/", "/dashboard"):
            response = client.get(path, follow_redirects=False)
            assert response.status_code == 200
            assert response.json() == {"web2": True}

        api = client.get("/api/private-contract", follow_redirects=False)
        assert api.status_code == 401
        assert api.json()["status"] == "unauthorized"

        private_page = client.get("/private-page", follow_redirects=False)
        assert private_page.status_code == 303
        assert private_page.headers["location"] == "/login?next=/private-page"


def test_public_verifier_requires_direct_web2_200_with_diagnostics() -> None:
    source = VERIFY.read_text(encoding="utf-8")

    assert 'public_status="$(' in source
    assert '--write-out \'%{http_code}\'' in source
    assert 'if [[ "$public_status" != "200" ]]' in source
    assert "PUBLIC_WEB2_HTTP_STATUS_FAILED" in source
    assert "PUBLIC_WEB2_HTTP_STATUS_OK" in source
    assert "PUBLIC_WEB2_CACHE_CONTROL_FAILED" in source
    assert "PUBLIC_WEB2_CACHE_CONTROL_OK" in source
    assert "PUBLIC_WEB2_ASSET_FAMILY_FAILED" in source
    assert '"$PUBLIC_URL/api/health"' in source


def test_public_verifier_checks_cache_control_semantically() -> None:
    source = VERIFY.read_text(encoding="utf-8")

    for token in ("no-store", "no-cache", "must-revalidate", "max-age=0"):
        assert token in source
    assert "required - tokens" in source
    assert "cache-control: no-store, no-cache, must-revalidate, max-age=0" not in source.lower()
