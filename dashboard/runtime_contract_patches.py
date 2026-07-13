"""Compatibility marker for the canonical Dashboard runtime.

Legacy runtime monkey-patches previously depended on synthetic news/demo helper
functions. Those helpers no longer exist. Canonical API owners now provide the
runtime contracts directly, so installation is intentionally idempotent and
side-effect free.
"""
from __future__ import annotations


def install_runtime_contract_patches() -> None:
    from . import dashboard_contracts_middleware as contracts

    if getattr(contracts, "_runtime_contract_patches_installed", False):
        return
    contracts._runtime_contract_patches_installed = True


__all__: tuple[str, ...] = ("install_runtime_contract_patches",)
