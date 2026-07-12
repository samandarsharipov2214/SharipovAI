from __future__ import annotations

import dashboard.ai_organ_state_api as organ_state


def test_module_probe_is_fail_closed_when_parent_is_not_a_package(monkeypatch) -> None:
    def raise_missing(_name: str):
        raise ModuleNotFoundError("parent module is not a package")

    monkeypatch.setattr(organ_state.importlib.util, "find_spec", raise_missing)

    assert organ_state._module_available("trading_intelligence.trade_gate") is False
