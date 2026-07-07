"""Custom exceptions for the Bybit integration package."""


class BybitClientError(Exception):
    """Base exception for Bybit client failures."""


class BybitHTTPError(BybitClientError):
    """Raised when the Bybit HTTP request fails."""


class BybitAPIError(BybitClientError):
    """Raised when the Bybit API returns an unsuccessful response."""
