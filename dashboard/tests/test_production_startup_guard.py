from __future__ import annotations

import pytest

import dashboard


def test_production_requires_explicit_auth_secret(monkeypatch) -> None:
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.delenv("RENDER", raising=False)
    monkeypatch.delenv("AUTH_SECRET", raising=False)

    with pytest.raises(RuntimeError, match="AUTH_SECRET is required"):
        dashboard._require_production_auth_secret()


def test_non_production_may_use_test_fallback(monkeypatch) -> None:
    monkeypatch.setenv("ENVIRONMENT", "test")
    monkeypatch.delenv("RENDER", raising=False)
    monkeypatch.delenv("AUTH_SECRET", raising=False)

    dashboard._require_production_auth_secret()
