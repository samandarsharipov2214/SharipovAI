"""SaaS settings for auth, billing, markets and persistence."""
from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache

_TRUE = {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class SaaSSettings:
    database_url: str
    jwt_secret: str
    jwt_algorithm: str
    jwt_ttl_seconds: int
    auth_cookie_name: str
    auth_cookie_secure: bool
    auth_cookie_samesite: str
    free_messages_per_month: int
    stripe_secret_key: str
    stripe_webhook_secret: str
    stripe_monthly_price_id: str
    stripe_publishable_key: str
    app_base_url: str
    coingecko_base_url: str
    coingecko_demo_api_key: str
    market_timeout_seconds: float
    market_cache_ttl_seconds: int


def _bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in _TRUE


@lru_cache(maxsize=1)
def get_saas_settings() -> SaaSSettings:
    environment = os.getenv("ENVIRONMENT", "").strip().lower()
    production = _bool_env("RENDER", False) or environment in {"prod", "production"}
    auth_secret = os.getenv("AUTH_SECRET", "").strip()
    jwt_secret = os.getenv("JWT_SECRET", "").strip() or auth_secret or "local-dev-jwt-secret-change-me"
    return SaaSSettings(
        database_url=os.getenv("DATABASE_URL", "sqlite:///./data/sharipovai_saas.sqlite3").strip(),
        jwt_secret=jwt_secret,
        jwt_algorithm=os.getenv("JWT_ALGORITHM", "HS256").strip() or "HS256",
        jwt_ttl_seconds=max(900, int(os.getenv("JWT_TTL_SECONDS", str(60 * 60 * 24 * 7)))),
        auth_cookie_name=os.getenv("AUTH_COOKIE_NAME", "sharipovai_access").strip() or "sharipovai_access",
        auth_cookie_secure=_bool_env("AUTH_COOKIE_SECURE", production),
        auth_cookie_samesite=os.getenv("AUTH_COOKIE_SAMESITE", "lax").strip().lower() or "lax",
        free_messages_per_month=max(1, int(os.getenv("FREE_MESSAGES_PER_MONTH", "25"))),
        stripe_secret_key=os.getenv("STRIPE_SECRET_KEY", "").strip(),
        stripe_webhook_secret=os.getenv("STRIPE_WEBHOOK_SECRET", "").strip(),
        stripe_monthly_price_id=os.getenv("STRIPE_MONTHLY_PRICE_ID", "").strip(),
        stripe_publishable_key=os.getenv("STRIPE_PUBLISHABLE_KEY", "").strip(),
        app_base_url=os.getenv("APP_BASE_URL", "http://127.0.0.1").strip().rstrip("/"),
        coingecko_base_url=os.getenv("COINGECKO_BASE_URL", "https://api.coingecko.com/api/v3").strip().rstrip("/"),
        coingecko_demo_api_key=os.getenv("COINGECKO_DEMO_API_KEY", "").strip(),
        market_timeout_seconds=float(os.getenv("MARKET_TIMEOUT_SECONDS", "8.0")),
        market_cache_ttl_seconds=max(5, int(os.getenv("MARKET_CACHE_TTL_SECONDS", "20"))),
    )


__all__ = ["SaaSSettings", "get_saas_settings"]
