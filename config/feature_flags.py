"""Central feature flags for gradual, reversible SharipovAI rollouts.

New risky capabilities must default to disabled. Environment variables are the
only activation mechanism so code can be deployed without becoming active.
"""
from __future__ import annotations

import os
from dataclasses import dataclass


_TRUE_VALUES = {"1", "true", "yes", "on"}


@dataclass(frozen=True, slots=True)
class FeatureFlag:
    name: str
    default: bool = False
    description: str = ""

    def enabled(self) -> bool:
        raw = os.getenv(self.name)
        if raw is None:
            return self.default
        return raw.strip().lower() in _TRUE_VALUES


FEATURES: dict[str, FeatureFlag] = {
    "bybit_websocket": FeatureFlag(
        "FEATURE_BYBIT_WEBSOCKET",
        default=False,
        description="Stream Bybit market/account updates over WebSocket.",
    ),
    "bybit_rsa_auth": FeatureFlag(
        "FEATURE_BYBIT_RSA_AUTH",
        default=False,
        description="Use RSA request signing for Bybit private APIs.",
    ),
    "bybit_preview_engine": FeatureFlag(
        "FEATURE_BYBIT_PREVIEW_ENGINE",
        default=False,
        description="Build validated, non-executing Bybit order previews.",
    ),
    "bybit_testnet_execution": FeatureFlag(
        "FEATURE_BYBIT_TESTNET_EXECUTION",
        default=False,
        description="Allow guarded order execution on Bybit Testnet only.",
    ),
    "bybit_live_execution": FeatureFlag(
        "FEATURE_BYBIT_LIVE_EXECUTION",
        default=False,
        description="Allow guarded live execution. Must remain disabled by default.",
    ),
}


def is_feature_enabled(name: str) -> bool:
    """Return a registered feature state and fail closed for unknown names."""
    feature = FEATURES.get(name)
    return feature.enabled() if feature else False


def feature_snapshot() -> dict[str, bool]:
    """Return current states without exposing environment values or secrets."""
    return {name: feature.enabled() for name, feature in FEATURES.items()}
