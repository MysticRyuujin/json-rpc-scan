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
    """Async HTTP client for making JSON-RPC requests.

    Retries transient failures (network errors, 5xx) with exponential
    backoff. 4xx is NOT retried — those are client-side errors that won't
    resolve by retrying.
    """

    def __init__(
        self,
        timeout: float = 60.0,
        max_concurrent: int = 10,
        *,
        max_retries: int = 3,
        retry_base_delay: float = 0.5,
    ) -> None:
        """Initialize the RPC client.

        Args:
            timeout: Request timeout in seconds.
            max_concurrent: Maximum number of concurrent requests.
            max_retries: How many times to retry on transient failure
                (RequestError or 5xx). 0 disables retry. Default 3.
            retry_base_delay: Initial delay between retries in seconds;
                each subsequent retry doubles this (so 3 retries with
                base 0.5s = 0.5, 1.0, 2.0). Default 0.5.
        """
        self.timeout = timeout
        self.max_retries = max_retries
        self.retry_base_delay = retry_base_delay
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
            self._client = None

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
            return await self._call_with_retry(endpoint, payload, headers)

    async def _call_with_retry(
        self,
        endpoint: Endpoint,
        payload: dict[str, Any],
        headers: dict[str, str],
    ) -> RPCResponse:
        """Post the payload with exponential-backoff retry on transient failure."""
        assert self._client is not None  # guarded by caller
        last_error: str = ""
        attempts = self.max_retries + 1

        for attempt in range(attempts):
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
                status = exc.response.status_code
                last_error = f"HTTP {status}: {exc.response.text}"
                # 4xx is a client bug — retrying won't help. 5xx may be transient.
                if status < 500:
                    break
            except httpx.RequestError as exc:
                last_error = str(exc)

            if attempt < attempts - 1:
                delay = self.retry_base_delay * (2**attempt)
                await asyncio.sleep(delay)

        return RPCResponse(
            endpoint=endpoint,
            request=payload,
            response={},
            error=last_error,
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
