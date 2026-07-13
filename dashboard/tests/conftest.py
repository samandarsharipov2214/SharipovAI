from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def dashboard_unit_test_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SHARIPOVAI_DISABLE_AUTH", "1")
