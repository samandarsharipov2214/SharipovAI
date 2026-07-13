from __future__ import annotations

from config.loader import DEFAULT_CONFIG_PATH, load_config


def test_default_config_loads_outside_project_cwd(monkeypatch, tmp_path) -> None:
    monkeypatch.chdir(tmp_path)

    config = load_config()

    assert DEFAULT_CONFIG_PATH.is_absolute()
    assert DEFAULT_CONFIG_PATH.exists()
    assert config.run_mode == "demo"
    assert config.market.exchange == "bybit"
    assert config.paper.initial_balance == 10000.0


def test_legacy_relative_default_path_falls_back_to_project_root(monkeypatch, tmp_path) -> None:
    monkeypatch.chdir(tmp_path)

    config = load_config("config/default.toml")

    assert config.run_mode == "demo"
    assert config.market.category == "spot"
