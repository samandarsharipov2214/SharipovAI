"""Long-term memory for news events that measurably moved market prices."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any, Iterable

from .unified_memory import (
    DEFAULT_RETENTION_DAYS,
    IMPACT_NEWS_RETENTION_DAYS,
    UnifiedMemory,
)


@dataclass(frozen=True, slots=True)
class MarketImpact:
    news_id: str
    title: str
    symbol: str
    price_before: float
    price_after: float
    change_percent: float
    direction: str
    tags: tuple[str, ...]
    material: bool
    retention_days: int


class MarketImpactMemory:
    """Stores outcomes and finds repeatable, evidence-backed reaction patterns."""

    def __init__(self, memory: UnifiedMemory | None = None, material_threshold_percent: float = 1.0) -> None:
        self.memory = memory or UnifiedMemory()
        self.material_threshold_percent = abs(float(material_threshold_percent))

    def record(
        self,
        *,
        title: str,
        symbol: str,
        price_before: float,
        price_after: float,
        source: str,
        tags: Iterable[str] = (),
        news_id: str | None = None,
        observed_horizon_minutes: int = 60,
        occurred_at: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> MarketImpact:
        if price_before <= 0 or price_after <= 0:
            raise ValueError("Market prices must be positive.")
        change = round(((price_after - price_before) / price_before) * 100, 6)
        material = abs(change) >= self.material_threshold_percent
        retention = IMPACT_NEWS_RETENTION_DAYS if material else DEFAULT_RETENTION_DAYS
        normalized_tags = tuple(sorted({self._normalize(tag) for tag in tags if str(tag).strip()}))
        identifier = news_id or self._identifier(title, symbol, occurred_at)
        direction = "up" if change > 0 else "down" if change < 0 else "flat"
        impact = MarketImpact(
            news_id=identifier,
            title=title.strip(),
            symbol=symbol.strip().upper(),
            price_before=float(price_before),
            price_after=float(price_after),
            change_percent=change,
            direction=direction,
            tags=normalized_tags,
            material=material,
            retention_days=retention,
        )
        self.memory.put(
            "market_news_impact",
            identifier,
            {
                "title": impact.title,
                "symbol": impact.symbol,
                "price_before": impact.price_before,
                "price_after": impact.price_after,
                "change_percent": impact.change_percent,
                "direction": impact.direction,
                "tags": list(impact.tags),
                "material": impact.material,
                "observed_horizon_minutes": int(observed_horizon_minutes),
                "occurred_at": occurred_at,
                "metadata": metadata or {},
            },
            source=source,
            category="impact_news" if material else "news_analysis",
            retention_days=retention,
            now=occurred_at,
        )
        return impact

    def similar_pattern(
        self,
        *,
        title: str,
        symbol: str,
        tags: Iterable[str] = (),
        minimum_similarity: float = 0.35,
    ) -> dict[str, Any]:
        query_tokens = self._tokens(title, tags)
        candidates: list[dict[str, Any]] = []
        for item in self.memory.list_namespace("market_news_impact"):
            value = item.value
            if str(value.get("symbol", "")).upper() != symbol.upper():
                continue
            candidate_tokens = self._tokens(str(value.get("title", "")), value.get("tags", []))
            similarity = self._jaccard(query_tokens, candidate_tokens)
            if similarity < minimum_similarity:
                continue
            candidates.append(
                {
                    "news_id": item.key,
                    "title": value.get("title"),
                    "similarity": round(similarity, 4),
                    "change_percent": float(value.get("change_percent", 0.0)),
                    "direction": value.get("direction", "flat"),
                    "material": bool(value.get("material")),
                }
            )
        candidates.sort(key=lambda row: (row["similarity"], abs(row["change_percent"])), reverse=True)
        material = [row for row in candidates if row["material"]]
        up = len([row for row in material if row["direction"] == "up"])
        down = len([row for row in material if row["direction"] == "down"])
        consistent = max(up, down)
        expected_direction = "unknown"
        confidence = 0.0
        if len(material) >= 2 and consistent >= 2:
            expected_direction = "up" if up > down else "down" if down > up else "mixed"
            confidence = round(consistent / len(material), 4)
        return {
            "symbol": symbol.upper(),
            "matches": candidates,
            "material_match_count": len(material),
            "expected_direction": expected_direction,
            "pattern_confidence": confidence,
            "usable_for_decision": len(material) >= 2 and confidence >= 0.66,
            "warning": "Historical similarity is evidence, not a guarantee of the next market move.",
        }

    @staticmethod
    def _identifier(title: str, symbol: str, occurred_at: int | None) -> str:
        raw = f"{symbol.upper()}|{title.strip().lower()}|{occurred_at or 0}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]

    @classmethod
    def _tokens(cls, title: str, tags: Iterable[str]) -> set[str]:
        text = " ".join([title, *[str(tag) for tag in tags]])
        return {cls._normalize(token) for token in re.findall(r"[\w-]+", text.lower()) if len(token) > 2}

    @staticmethod
    def _normalize(value: str) -> str:
        return str(value).strip().lower().replace(" ", "_")

    @staticmethod
    def _jaccard(left: set[str], right: set[str]) -> float:
        if not left or not right:
            return 0.0
        return len(left & right) / len(left | right)
