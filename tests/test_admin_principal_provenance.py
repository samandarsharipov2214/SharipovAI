from fastapi import HTTPException

from dashboard.auth import dependencies


def test_admin_principal_uses_identity_returned_by_require_admin(monkeypatch):
    request = object()

    monkeypatch.setattr(dependencies, "require_admin", lambda candidate: "verified-admin")

    principal = dependencies.admin_principal(request)

    assert principal.username == "verified-admin"
    assert principal.authenticated is True
    assert principal.admin is True


def test_admin_principal_preserves_fail_closed_auth_error(monkeypatch):
    request = object()

    def deny(_request):
        raise HTTPException(status_code=401, detail={"status": "unauthorized"})

    monkeypatch.setattr(dependencies, "require_admin", deny)

    try:
        dependencies.admin_principal(request)
    except HTTPException as exc:
        assert exc.status_code == 401
        assert exc.detail == {"status": "unauthorized"}
    else:
        raise AssertionError("admin_principal must fail closed when require_admin rejects")


def test_admin_principal_bounds_verified_username(monkeypatch):
    request = object()
    username = "a" * 256

    monkeypatch.setattr(dependencies, "require_admin", lambda candidate: username)

    principal = dependencies.admin_principal(request)

    assert principal.username == "a" * 128
