from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from fastapi import FastAPI

from dashboard.evidence_vault_api import install_evidence_vault_api
from dashboard.learning_os_api import install_learning_os_api
from dashboard.source_status_compat_api import install_source_status_compat_api


ROOT = Path(__file__).resolve().parents[1]
WEB2 = ROOT / "dashboard" / "static" / "web2"


def _endpoint(app: FastAPI, path: str) -> Callable[..., dict[str, Any]]:
    for route in app.routes:
        if getattr(route, "path", "") == path:
            return route.endpoint
    raise AssertionError(f"route missing: {path}")


def test_learning_and_evidence_status_routes_return_persistent_empty_safe_contracts(tmp_path, monkeypatch):
    monkeypatch.setenv("LEARNING_MEMORY_DB", str(tmp_path / "learning.sqlite3"))
    monkeypatch.setenv("EVIDENCE_VAULT_DB", str(tmp_path / "evidence.sqlite3"))

    app = FastAPI()
    install_learning_os_api(app)
    install_evidence_vault_api(app)
    install_source_status_compat_api(app)

    learning = _endpoint(app, "/api/learning-os/status")()
    evidence = _endpoint(app, "/api/evidence-vault/recent")()

    assert learning["status"] == "ok"
    assert learning["source"] == "learning_memory"
    assert isinstance(learning["items"], list)
    assert isinstance(learning["summary"], dict)

    assert evidence["status"] == "ok"
    assert evidence["source"] == "evidence_vault"
    assert isinstance(evidence["items"], list)
    assert isinstance(evidence["summary"], dict)


def test_web2_counts_core_services_and_marks_private_bybit_optional():
    core = (WEB2 / "web2.js").read_text(encoding="utf-8")
    system = (WEB2 / "system_status_v11.js").read_text(encoding="utf-8")

    assert "/api/learning-os/status" in core
    assert "/api/evidence-vault/recent" in core
    assert "/api/exchange/account/status" in core
    assert "required: false" in core
    assert "основных API" in core
    assert "Часть источников недоступна (" not in core

    assert "/api/exchange/account/status" in system
    assert "НЕ НАСТРОЕН" in system
    assert "не считается поломкой" in system
    assert "основных источников отвечают" in system
