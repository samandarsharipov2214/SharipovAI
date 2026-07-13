"""Repository-wide pytest isolation defaults.

Production and CI remain fail-closed. Functional tests explicitly opt into the
factory auth bypass unless an auth-focused test overrides or removes the
variable with ``monkeypatch``.
"""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _default_test_auth_bypass(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SHARIPOVAI_DISABLE_AUTH", "1")
