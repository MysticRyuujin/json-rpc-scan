"""Async JSON-RPC client for Ethereum endpoints."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

import httpx


@dataclass
class Endpoint:
    """Represents a JSON-RPC endpoint with a name and URL."""

    name: str
    url: str
    headers: dict[str, str] | None = None


@dataclass
class RPCResponse:
    """Wraps a JSON-RPC response with metadata."""

    endpoint: Endpoint
    request: dict[str, Any]
    response: dict[str, Any]
    error: str | None = None


class RPCClient:
    """Async HTTP client for making JSON-RPC requests."""

    def __init__(
        self,
        timeout: float = 60.0,
        max_concurrent: int = 10,
    ) -> None:
        """Initialize the RPC client.

        Args:
            timeout: Request timeout in seconds.
            max_concurrent: Maximum number of concurrent requests.
        """
        self.timeout = timeout
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> RPCClient:
        """Enter async context."""
        self._client = httpx.AsyncClient(timeout=self.timeout)
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: object,
    ) -> None:
        """Exit async context."""
        if self._client:
            await self._client.aclose()

    async def call(
        self,
        endpoint: Endpoint,
        method: str,
        params: list[Any] | None = None,
        request_id: int = 1,
    ) -> RPCResponse:
        """Make a single JSON-RPC call.

        Args:
            endpoint: The endpoint to call.
            method: The JSON-RPC method name.
            params: Optional parameters for the method.
            request_id: The request ID.

        Returns:
            RPCResponse containing the result or error.
        """
        if self._client is None:
            msg = "Client not initialized. Use 'async with' context manager."
            raise RuntimeError(msg)

        payload = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params or [],
            "id": request_id,
        }

        headers = {"Content-Type": "application/json"}
        if endpoint.headers:
            headers.update(endpoint.headers)

        async with self._semaphore:
            try:
                response = await self._client.post(
                    endpoint.url,
                    json=payload,
                    headers=headers,
                )
                response.raise_for_status()
                return RPCResponse(
                    endpoint=endpoint,
                    request=payload,
                    response=response.json(),
                )
            except httpx.HTTPStatusError as exc:
                return RPCResponse(
                    endpoint=endpoint,
                    request=payload,
                    response={},
                    error=f"HTTP {exc.response.status_code}: {exc.response.text}",
                )
            except httpx.RequestError as exc:
                return RPCResponse(
                    endpoint=endpoint,
                    request=payload,
                    response={},
                    error=str(exc),
                )

    async def call_both(
        self,
        endpoints: tuple[Endpoint, Endpoint],
        method: str,
        params: list[Any] | None = None,
        request_id: int = 1,
    ) -> tuple[RPCResponse, RPCResponse]:
        """Make the same JSON-RPC call to both endpoints concurrently.

        Args:
            endpoints: Tuple of two endpoints to compare.
            method: The JSON-RPC method name.
            params: Optional parameters for the method.
            request_id: The request ID.

        Returns:
            Tuple of two RPCResponse objects.
        """
        results = await asyncio.gather(
            self.call(endpoints[0], method, params, request_id),
            self.call(endpoints[1], method, params, request_id),
        )
        return results[0], results[1]

    async def get_block_number(self, endpoint: Endpoint) -> int | None:
        """Get the latest block number from an endpoint.

        Args:
            endpoint: The endpoint to query.

        Returns:
            The latest block number, or None on error.
        """
        response = await self.call(endpoint, "eth_blockNumber")
        if response.error:
            return None
        result = response.response.get("result")
        if result:
            return int(result, 16)
        return None

    async def get_block(
        self,
        endpoint: Endpoint,
        block_number: int,
        full_transactions: bool = True,
    ) -> dict[str, Any] | None:
        """Get a block by number.

        Args:
            endpoint: The endpoint to query.
            block_number: The block number.
            full_transactions: If True, include full transaction objects.

        Returns:
            The block data, or None on error.
        """
        response = await self.call(
            endpoint,
            "eth_getBlockByNumber",
            [hex(block_number), full_transactions],
        )
        if response.error:
            return None
        return response.response.get("result")

    async def get_transaction_receipt(
        self,
        endpoint: Endpoint,
        tx_hash: str,
    ) -> dict[str, Any] | None:
        """Get a transaction receipt by hash.

        Args:
            endpoint: The endpoint to query.
            tx_hash: The transaction hash.

        Returns:
            The receipt data, or None on error.
        """
        response = await self.call(
            endpoint,
            "eth_getTransactionReceipt",
            [tx_hash],
        )
        if response.error:
            return None
        return response.response.get("result")
