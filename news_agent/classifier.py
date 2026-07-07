"""Deterministic keyword-based news classifier."""

from __future__ import annotations

from data_layer.models import DataItem

from .impact import ImpactScorer
from .models import NewsClassification


class NewsClassifier:
    """Classifies news category and sentiment using keyword dictionaries."""

    CATEGORY_KEYWORDS: dict[str, tuple[str, ...]] = {
        "Bitcoin": ("bitcoin", "btc"),
        "Ethereum": ("ethereum", "eth"),
        "Altcoins": ("altcoin", "altcoins", "solana", "sol", "xrp", "cardano"),
        "Macro": ("fed", "inflation", "rate", "gdp", "cpi", "employment"),
        "Regulation": ("sec", "regulation", "regulator", "ban", "approval", "law"),
        "Security": ("hack", "exploit", "breach", "stolen", "security"),
        "Exchange": ("exchange", "binance", "coinbase", "kraken", "bybit"),
        "General": (),
    }
    BULLISH_KEYWORDS: tuple[str, ...] = (
        "approval",
        "approved",
        "surge",
        "rally",
        "gain",
        "growth",
        "inflow",
        "bullish",
    )
    BEARISH_KEYWORDS: tuple[str, ...] = (
        "hack",
        "ban",
        "bankruptcy",
        "liquidation",
        "selloff",
        "loss",
        "bearish",
        "outflow",
    )

    def __init__(self, impact_scorer: ImpactScorer | None = None) -> None:
        """Initialize the classifier.

        Args:
            impact_scorer: Optional impact scorer dependency.
        """

        self._impact_scorer = impact_scorer or ImpactScorer()

    def classify(self, item: DataItem) -> NewsClassification:
        """Classify a news item.

        Args:
            item: Data item to classify.

        Returns:
            News classification.
        """

        return NewsClassification(
            category=self.category(item),
            sentiment=self.sentiment(item),
            impact_score=self._impact_scorer.score(item),
        )

    def category(self, item: DataItem) -> str:
        """Classify news category.

        Args:
            item: Data item to classify.

        Returns:
            Category name.
        """

        text = self._text(item)
        for category, keywords in self.CATEGORY_KEYWORDS.items():
            if any(keyword in text for keyword in keywords):
                return category
        return "General"

    def sentiment(self, item: DataItem) -> str:
        """Classify news sentiment.

        Args:
            item: Data item to classify.

        Returns:
            Sentiment label.
        """

        text = self._text(item)
        bullish_matches = sum(1 for keyword in self.BULLISH_KEYWORDS if keyword in text)
        bearish_matches = sum(1 for keyword in self.BEARISH_KEYWORDS if keyword in text)

        if bullish_matches > bearish_matches:
            return "Bullish"

        if bearish_matches > bullish_matches:
            return "Bearish"

        return "Neutral"

    def _text(self, item: DataItem) -> str:
        """Return normalized searchable text for a news item."""

        return f"{item.title} {item.content}".lower()
