"""Small runtime patches for legacy views backed by canonical system data."""
from __future__ import annotations

from typing import Any


def install_runtime_contract_patches() -> None:
    from . import dashboard_contracts_middleware as contracts

    if getattr(contracts, "_runtime_contract_patches_installed", False):
        return
    contracts._runtime_contract_patches_installed = True

    original_ai_bots = contracts._ai_bots_payload
    original_social_news = contracts._social_news_payload
    original_social_rss = contracts._social_rss_refresh

    def ai_bots_payload() -> dict[str, Any]:
        payload = original_ai_bots()
        bots = payload.get("bots", payload.get("agents", []))
        if not isinstance(bots, list):
            bots = []
        active = sum(
            str(bot.get("status", "")).lower() in {"active", "working", "ok", "healthy"}
            for bot in bots
            if isinstance(bot, dict)
        )
        warnings = sum(
            str(bot.get("status", "")).lower() not in {"active", "working", "ok", "healthy"}
            for bot in bots
            if isinstance(bot, dict)
        )
        summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
        summary.update(
            {
                "total_bots": len(bots),
                "canonical_ai_count": len(bots),
                "active": active,
                "warnings": warnings,
            }
        )
        payload["summary"] = summary
        payload["bots"] = bots
        payload["truth_policy"] = "No decorative active count; statuses are reported exactly as supplied by the runtime source."
        return payload

    def social_news_payload() -> dict[str, Any]:
        payload = original_social_news()
        news = payload.get("news", {}) if isinstance(payload.get("news"), dict) else {}
        summary = news.get("summary", {}) if isinstance(news, dict) else {}
        if int(summary.get("total", 0) or 0) > 0:
            return payload
        # Do not invent a bootstrap article merely to make the dashboard look
        # populated. Absence of verified news is a real state and must remain so.
        payload["source_mode"] = "no_verified_live_news"
        payload["synthetic_fallback_used"] = False
        return payload

    def social_rss_refresh(data: dict[str, Any]) -> dict[str, Any]:
        result = original_social_rss(data)
        if result.get("status") == "ok" and result.get("items"):
            result["synthetic_fallback_used"] = False
            return result
        # The old isolated-feed fallback replaced source publish time with
        # datetime.now(), which could make stale news look current. Fail closed
        # instead and let canonical News Intelligence own live refresh.
        result["fallback"] = "disabled_to_preserve_news_freshness"
        result["synthetic_fallback_used"] = False
        return result

    contracts._ai_bots_payload = ai_bots_payload
    contracts._social_news_payload = social_news_payload
    contracts._social_rss_refresh = social_rss_refresh


__all__: tuple[str, ...] = ("install_runtime_contract_patches",)
