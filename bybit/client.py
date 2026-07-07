"""Async Bybit V5 market-data client.

This module provides unauthenticated market-data access only. It does not
include API-key authentication, trading operations, or business logic.
"""

from __future__ import annotations

from typing import Any, Mapping

import httpx

from .exceptions import BybitAPIError, BybitHTTPError
from .models import BybitResponse, InstrumentInfo, ServerTime, TickerInfo


class BybitClient:
    """Async client for public Bybit V5 market-data endpoints."""

    DEFAULT_BASE_URL: str = "https://api.bybit.com"
    DEFAULT_TIMEOUT_SECONDS: float = 10.0

    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        """Initialize the Bybit client.

        Args:
            base_url: Base URL for the Bybit API.
            timeout: Request timeout in seconds.
            client: Optional externally managed ``httpx.AsyncClient``.
        """

        self._base_url = base_url.rstrip("/")
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            base_url=self._base_url,
            timeout=httpx.Timeout(timeout),
            headers={"Accept": "application/json"},
        )

    async def __aenter__(self) -> BybitClient:
        """Enter the async context manager.

        Returns:
            The active client instance.
        """

        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: object | None,
    ) -> None:
        """Exit the async context manager and close owned resources.

        Args:
            exc_type: Exception type, when an exception occurred.
            exc_value: Exception instance, when an exception occurred.
            traceback: Exception traceback, when an exception occurred.
        """

        await self.close()

    async def close(self) -> None:
        """Close the underlying HTTP client when owned by this instance."""

        if self._owns_client:
            await self._client.aclose()

    async def ping(self) -> bool:
        """Check whether the public Bybit API is reachable.

        Returns:
            ``True`` when Bybit returns a successful public API response.

        Raises:
            BybitClientError: If the request or API response fails.
        """

        await self.get_server_time()
        return True

    async def get_server_time(self) -> ServerTime:
        """Fetch Bybit server time.

        Returns:
            Parsed server time response.

        Raises:
            BybitClientError: If the request or API response fails.
        """

        response = await self._get("/v5/market/time")
        return ServerTime.from_result(response.result)

    async def get_instruments(self, category: str = "spot") -> list[InstrumentInfo]:
        """Fetch public instrument metadata.

        Args:
            category: Bybit instrument category, such as ``spot``, ``linear``,
                ``inverse``, or ``option``.

        Returns:
            List of parsed instrument metadata.

        Raises:
            BybitClientError: If the request or API response fails.
        """

        response = await self._get(
            "/v5/market/instruments-info",
            params={"category": category},
        )
        instruments = response.result.get("list", [])
        if not isinstance(instruments, list):
            return []

        return [
            InstrumentInfo.from_payload(category=category, payload=item)
            for item in instruments
            if isinstance(item, Mapping)
        ]

    async def get_tickers(self, category: str = "spot") -> list[TickerInfo]:
        """Fetch public ticker metadata.

        Args:
            category: Bybit ticker category, such as ``spot``, ``linear``,
                ``inverse``, or ``option``.

        Returns:
            List of parsed ticker metadata.

        Raises:
            BybitClientError: If the request or API response fails.
        """

        response = await self._get(
            "/v5/market/tickers",
            params={"category": category},
        )
        tickers = response.result.get("list", [])
        if not isinstance(tickers, list):
            return []

        return [
            TickerInfo.from_payload(category=category, payload=item)
            for item in tickers
            if isinstance(item, Mapping)
        ]

    async def _get(
        self,
        path: str,
        params: Mapping[str, Any] | None = None,
    ) -> BybitResponse:
        """Send a GET request to the Bybit V5 API.

        Args:
            path: API path.
            params: Optional query parameters.

        Returns:
            Parsed Bybit response wrapper.

        Raises:
            BybitHTTPError: If the HTTP request fails.
            BybitAPIError: If Bybit returns a non-success response code.
        """

        try:
            http_response = await self._client.get(path, params=params)
            http_response.raise_for_status()
        except httpx.HTTPError as exc:
            raise BybitHTTPError(f"Bybit HTTP request failed: {exc}") from exc

        payload = _json_mapping(http_response)
        response = BybitResponse.from_payload(payload)
        if response.ret_code != 0:
            raise BybitAPIError(
                f"Bybit API request failed with code {response.ret_code}: "
                f"{response.ret_msg}"
            )

        return response


def _json_mapping(response: httpx.Response) -> Mapping[str, Any]:
    """Read a response JSON body as a mapping.

    Args:
        response: HTTP response returned by httpx.

    Returns:
        JSON mapping payload.

    Raises:
        BybitHTTPError: If the response body is not a JSON object.
    """

    try:
        payload = response.json()
    except ValueError as exc:
        raise BybitHTTPError("Bybit response body is not valid JSON.") from exc

    if not isinstance(payload, Mapping):
        raise BybitHTTPError("Bybit response body is not a JSON object.")

    return payload
