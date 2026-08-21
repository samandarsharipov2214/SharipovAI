from __future__ import annotations

from dashboard.settings_saas import get_saas_settings
from storage.project_database import ProjectDatabase


def test_default_saas_database_matches_canonical_project_database(monkeypatch, tmp_path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("SHARIPOVAI_DATABASE_REQUIRED", raising=False)
    data_dir = tmp_path / "shared-data"
    monkeypatch.setenv("SHARIPOVAI_DATA_DIR", str(data_dir))
    get_saas_settings.cache_clear()
    try:
        settings = get_saas_settings()
        project_db = ProjectDatabase()
        assert settings.database_url == project_db.dsn
        assert settings.database_url.endswith("/sharipovai_shared.db")
        assert data_dir.is_dir()
    finally:
        get_saas_settings.cache_clear()


def test_existing_legacy_fallback_database_is_preserved(monkeypatch, tmp_path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    legacy = tmp_path / "data" / "sharipovai_saas.sqlite3"
    legacy.parent.mkdir(parents=True)
    legacy.touch()
    monkeypatch.setenv("SHARIPOVAI_DATA_DIR", str(tmp_path / "shared-data"))
    get_saas_settings.cache_clear()
    try:
        assert get_saas_settings().database_url == "sqlite:///./data/sharipovai_saas.sqlite3"
    finally:
        get_saas_settings.cache_clear()


def test_explicit_database_url_still_wins(monkeypatch) -> None:
    explicit = "sqlite:///explicit-test.db"
    monkeypatch.setenv("DATABASE_URL", explicit)
    monkeypatch.setenv("SHARIPOVAI_DATABASE_REQUIRED", "1")
    monkeypatch.setenv("SHARIPOVAI_DATA_DIR", "ignored-shared-data")
    get_saas_settings.cache_clear()
    try:
        assert get_saas_settings().database_url == explicit
        assert ProjectDatabase().dsn == explicit
    finally:
        get_saas_settings.cache_clear()
