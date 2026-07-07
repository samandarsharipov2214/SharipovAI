"""Typed data models for Bybit V5 market-data responses."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class BybitResponse:
    """Generic Bybit V5 API response wrapper.

    Attributes:
        ret_code: Bybit response code.
        ret_msg: Bybit response message.
        result: Response payload.
        time: Response timestamp from Bybit, when present.
    """

    ret_code: int
    ret_msg: str
    result: Mapping[str, Any]
    time: int | None = None

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> BybitResponse:
        """Create a response wrapper from a raw Bybit payload.

        Args:
            payload: Raw JSON payload returned by Bybit.

        Returns:
            Parsed response wrapper.
        """

        return cls(
            ret_code=int(payload.get("retCode", -1)),
            ret_msg=str(payload.get("retMsg", "")),
            result=_as_mapping(payload.get("result", {})),
            time=_as_optional_int(payload.get("time")),
        )


@dataclass(frozen=True, slots=True)
class ServerTime:
    """Bybit server time response.

    Attributes:
        time_second: Server time in seconds.
        time_nano: Server time in nanoseconds.
    """

    time_second: int
    time_nano: int

    @classmethod
    def from_result(cls, result: Mapping[str, Any]) -> ServerTime:
        """Create server time from a Bybit result payload.

        Args:
            result: ``result`` object from the Bybit V5 time endpoint.

        Returns:
            Parsed server time model.
        """

        return cls(
            time_second=int(result.get("timeSecond", 0)),
            time_nano=int(result.get("timeNano", 0)),
        )


@dataclass(frozen=True, slots=True)
class InstrumentInfo:
    """Bybit instrument metadata.

    Attributes:
        category: Instrument category requested from Bybit.
        symbol: Instrument symbol.
        base_coin: Base asset code, when present.
        quote_coin: Quote asset code, when present.
        status: Instrument status, when present.
        raw: Original instrument payload.
    """

    category: str
    symbol: str
    base_coin: str | None = None
    quote_coin: str | None = None
    status: str | None = None
    raw: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def from_payload(cls, category: str, payload: Mapping[str, Any]) -> InstrumentInfo:
        """Create instrument metadata from a raw Bybit item.

        Args:
            category: Instrument category used for the request.
            payload: Raw instrument object returned by Bybit.

        Returns:
            Parsed instrument metadata.
        """

        return cls(
            category=category,
            symbol=str(payload.get("symbol", "")),
            base_coin=_as_optional_str(payload.get("baseCoin")),
            quote_coin=_as_optional_str(payload.get("quoteCoin")),
            status=_as_optional_str(payload.get("status")),
            raw=dict(payload),
        )


@dataclass(frozen=True, slots=True)
class TickerInfo:
    """Bybit ticker metadata.

    Attributes:
        category: Ticker category requested from Bybit.
        symbol: Instrument symbol.
        last_price: Last traded price, when present.
        bid_price: Best bid price, when present.
        ask_price: Best ask price, when present.
        price_24h_change_percent: 24-hour price change percentage, when present.
        volume_24h: 24-hour volume, when present.
        turnover_24h: 24-hour turnover, when present.
        raw: Original ticker payload.
    """

    category: str
    symbol: str
    last_price: str | None = None
    bid_price: str | None = None
    ask_price: str | None = None
    price_24h_change_percent: str | None = None
    volume_24h: str | None = None
    turnover_24h: str | None = None
    raw: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def from_payload(cls, category: str, payload: Mapping[str, Any]) -> TickerInfo:
        """Create ticker metadata from a raw Bybit item.

        Args:
            category: Ticker category used for the request.
            payload: Raw ticker object returned by Bybit.

        Returns:
            Parsed ticker metadata.
        """

        return cls(
            category=category,
            symbol=str(payload.get("symbol", "")),
            last_price=_as_optional_str(payload.get("lastPrice")),
            bid_price=_as_optional_str(payload.get("bid1Price")),
            ask_price=_as_optional_str(payload.get("ask1Price")),
            price_24h_change_percent=_as_optional_str(payload.get("price24hPcnt")),
            volume_24h=_as_optional_str(payload.get("volume24h")),
            turnover_24h=_as_optional_str(payload.get("turnover24h")),
            raw=dict(payload),
        )


def _as_mapping(value: Any) -> Mapping[str, Any]:
    """Return a mapping value or an empty mapping.

    Args:
        value: Candidate value.

    Returns:
        Mapping representation of the value.
    """

    if isinstance(value, Mapping):
        return value
    return {}


def _as_optional_int(value: Any) -> int | None:
    """Convert a value to an optional integer.

    Args:
        value: Candidate integer value.

    Returns:
        Integer value or ``None``.
    """

    if value is None:
        return None
    return int(value)


def _as_optional_str(value: Any) -> str | None:
    """Convert a value to an optional string.

    Args:
        value: Candidate string value.

    Returns:
        String value or ``None``.
    """

    if value is None:
        return None
    return str(value)
