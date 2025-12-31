"""Tests for the client module."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from json_rpc_scan.client import Endpoint, RPCClient, RPCResponse


class TestEndpoint:
    """Tests for Endpoint dataclass."""

    def test_endpoint_creation(self):
        """Test creating an Endpoint."""
        ep = Endpoint(name="test", url="http://localhost:8545")
        assert ep.name == "test"
        assert ep.url == "http://localhost:8545"
        assert ep.headers is None

    def test_endpoint_with_headers(self):
        """Test creating an Endpoint with headers."""
        headers = {"Authorization": "Bearer token"}
        ep = Endpoint(name="test", url="http://localhost:8545", headers=headers)
        assert ep.headers == headers


class TestRPCResponse:
    """Tests for RPCResponse dataclass."""

    def test_response_creation(self):
        """Test creating an RPCResponse."""
        ep = Endpoint(name="test", url="http://localhost:8545")
        request = {"jsonrpc": "2.0", "method": "eth_blockNumber", "params": [], "id": 1}
        response = {"jsonrpc": "2.0", "id": 1, "result": "0x10"}

        rpc_resp = RPCResponse(endpoint=ep, request=request, response=response)

        assert rpc_resp.endpoint == ep
        assert rpc_resp.request == request
        assert rpc_resp.response == response
        assert rpc_resp.error is None

    def test_response_with_error(self):
        """Test creating an RPCResponse with an error."""
        ep = Endpoint(name="test", url="http://localhost:8545")
        request = {"jsonrpc": "2.0", "method": "eth_blockNumber", "params": [], "id": 1}

        rpc_resp = RPCResponse(
            endpoint=ep,
            request=request,
            response={},
            error="Connection refused",
        )

        assert rpc_resp.error == "Connection refused"
        assert rpc_resp.response == {}


class TestRPCClient:
    """Tests for RPCClient class."""

    @pytest.mark.asyncio
    async def test_context_manager(self):
        """Test RPCClient as async context manager."""
        client = RPCClient()
        assert client._client is None
        async with client as ctx_client:
            assert ctx_client is client
            assert client._client is not None
        # After exiting, client should be closed and set to None
        assert client._client is None

    @pytest.mark.asyncio
    async def test_call_success(self):
        """Test successful RPC call."""
        endpoint = Endpoint(name="test", url="http://localhost:8545")
        mock_response = MagicMock()
        mock_response.json.return_value = {"jsonrpc": "2.0", "id": 1, "result": "0x10"}
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)

        client = RPCClient()
        client._client = mock_client

        response = await client.call(endpoint, "eth_blockNumber")

        assert response.endpoint == endpoint
        assert response.response == {"jsonrpc": "2.0", "id": 1, "result": "0x10"}
        assert response.error is None
        assert response.request["method"] == "eth_blockNumber"
        assert response.request["params"] == []
        mock_client.post.assert_called_once()

    @pytest.mark.asyncio
    async def test_call_with_params(self):
        """Test RPC call with parameters."""
        endpoint = Endpoint(name="test", url="http://localhost:8545")
        mock_response = MagicMock()
        mock_response.json.return_value = {"jsonrpc": "2.0", "id": 1, "result": "0x123"}
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)

        client = RPCClient()
        client._client = mock_client

        params = ["0x1", True]
        response = await client.call(endpoint, "eth_getBlockByNumber", params=params)

        assert response.request["params"] == params
        call_args = mock_client.post.call_args
        assert call_args[1]["json"]["params"] == params

    @pytest.mark.asyncio
    async def test_call_with_custom_request_id(self):
        """Test RPC call with custom request ID."""
        endpoint = Endpoint(name="test", url="http://localhost:8545")
        mock_response = MagicMock()
        mock_response.json.return_value = {"jsonrpc": "2.0", "id": 42, "result": "0x10"}
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)

        client = RPCClient()
        client._client = mock_client

        response = await client.call(endpoint, "eth_blockNumber", request_id=42)

        assert response.request["id"] == 42

    @pytest.mark.asyncio
    async def test_call_with_headers(self):
        """Test RPC call with custom endpoint headers."""
        headers = {"Authorization": "Bearer token"}
        endpoint = Endpoint(name="test", url="http://localhost:8545", headers=headers)
        mock_response = MagicMock()
        mock_response.json.return_value = {"jsonrpc": "2.0", "id": 1, "result": "0x10"}
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)

        client = RPCClient()
        client._client = mock_client

        await client.call(endpoint, "eth_blockNumber")

        call_args = mock_client.post.call_args
        assert "Authorization" in call_args[1]["headers"]
        assert call_args[1]["headers"]["Authorization"] == "Bearer token"

    @pytest.mark.asyncio
    async def test_call_http_error(self):
        """Test RPC call with HTTP error."""
        endpoint = Endpoint(name="test", url="http://localhost:8545")
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"

        mock_client = AsyncMock()
        http_error = httpx.HTTPStatusError(
            "Server Error", request=MagicMock(), response=mock_response
        )
        mock_client.post = AsyncMock(side_effect=http_error)

        client = RPCClient()
        client._client = mock_client

        response = await client.call(endpoint, "eth_blockNumber")

        assert response.error is not None
        assert "HTTP 500" in response.error
        assert response.response == {}

    @pytest.mark.asyncio
    async def test_call_request_error(self):
        """Test RPC call with request error."""
        endpoint = Endpoint(name="test", url="http://localhost:8545")

        mock_client = AsyncMock()
        request_error = httpx.RequestError("Connection refused", request=MagicMock())
        mock_client.post = AsyncMock(side_effect=request_error)

        client = RPCClient()
        client._client = mock_client

        response = await client.call(endpoint, "eth_blockNumber")

        assert response.error == "Connection refused"
        assert response.response == {}

    @pytest.mark.asyncio
    async def test_call_without_context_manager(self):
        """Test that call raises error if client not initialized."""
        endpoint = Endpoint(name="test", url="http://localhost:8545")
        client = RPCClient()

        with pytest.raises(RuntimeError, match="Client not initialized"):
            await client.call(endpoint, "eth_blockNumber")

    @pytest.mark.asyncio
    async def test_call_both(self):
        """Test calling both endpoints concurrently."""
        endpoint1 = Endpoint(name="test1", url="http://localhost:8545")
        endpoint2 = Endpoint(name="test2", url="http://localhost:8546")

        mock_response1 = MagicMock()
        mock_response1.json.return_value = {"jsonrpc": "2.0", "id": 1, "result": "0x10"}
        mock_response1.raise_for_status = MagicMock()

        mock_response2 = MagicMock()
        mock_response2.json.return_value = {"jsonrpc": "2.0", "id": 1, "result": "0x20"}
        mock_response2.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=[mock_response1, mock_response2])

        client = RPCClient()
        client._client = mock_client

        resp1, resp2 = await client.call_both((endpoint1, endpoint2), "eth_blockNumber")

        assert resp1.endpoint == endpoint1
        assert resp1.response["result"] == "0x10"
        assert resp2.endpoint == endpoint2
        assert resp2.response["result"] == "0x20"
        assert mock_client.post.call_count == 2

    @pytest.mark.asyncio
    async def test_get_block_number_success(self):
        """Test getting block number successfully."""
        endpoint = Endpoint(name="test", url="http://localhost:8545")
        mock_response = MagicMock()
        mock_response.json.return_value = {"jsonrpc": "2.0", "id": 1, "result": "0x10"}
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)

        client = RPCClient()
        client._client = mock_client

        block_number = await client.get_block_number(endpoint)

        assert block_number == 16  # 0x10 = 16

    @pytest.mark.asyncio
    async def test_get_block_number_error(self):
        """Test getting block number with error."""
        endpoint = Endpoint(name="test", url="http://localhost:8545")

        mock_client = AsyncMock()
        request_error = httpx.RequestError("Connection refused", request=MagicMock())
        mock_client.post = AsyncMock(side_effect=request_error)

        client = RPCClient()
        client._client = mock_client

        block_number = await client.get_block_number(endpoint)

        assert block_number is None

    @pytest.mark.asyncio
    async def test_get_block_number_no_result(self):
        """Test getting block number when result is missing."""
        endpoint = Endpoint(name="test", url="http://localhost:8545")
        mock_response = MagicMock()
        mock_response.json.return_value = {"jsonrpc": "2.0", "id": 1}
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)

        client = RPCClient()
        client._client = mock_client

        block_number = await client.get_block_number(endpoint)

        assert block_number is None

    @pytest.mark.asyncio
    async def test_get_block_success(self):
        """Test getting block successfully."""
        endpoint = Endpoint(name="test", url="http://localhost:8545")
        block_data = {"number": "0x1", "hash": "0xabc"}
        mock_response = MagicMock()
        mock_response.json.return_value = {"jsonrpc": "2.0", "id": 1, "result": block_data}
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)

        client = RPCClient()
        client._client = mock_client

        block = await client.get_block(endpoint, 1)

        assert block == block_data
        call_args = mock_client.post.call_args
        assert call_args[1]["json"]["params"] == ["0x1", True]

    @pytest.mark.asyncio
    async def test_get_block_with_full_transactions_false(self):
        """Test getting block with full_transactions=False."""
        endpoint = Endpoint(name="test", url="http://localhost:8545")
        mock_response = MagicMock()
        mock_response.json.return_value = {"jsonrpc": "2.0", "id": 1, "result": {}}
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)

        client = RPCClient()
        client._client = mock_client

        await client.get_block(endpoint, 1, full_transactions=False)

        call_args = mock_client.post.call_args
        assert call_args[1]["json"]["params"] == ["0x1", False]

    @pytest.mark.asyncio
    async def test_get_block_error(self):
        """Test getting block with error."""
        endpoint = Endpoint(name="test", url="http://localhost:8545")

        mock_client = AsyncMock()
        request_error = httpx.RequestError("Connection refused", request=MagicMock())
        mock_client.post = AsyncMock(side_effect=request_error)

        client = RPCClient()
        client._client = mock_client

        block = await client.get_block(endpoint, 1)

        assert block is None

    @pytest.mark.asyncio
    async def test_get_transaction_receipt_success(self):
        """Test getting transaction receipt successfully."""
        endpoint = Endpoint(name="test", url="http://localhost:8545")
        receipt_data = {"transactionHash": "0xabc", "status": "0x1"}
        mock_response = MagicMock()
        mock_response.json.return_value = {"jsonrpc": "2.0", "id": 1, "result": receipt_data}
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)

        client = RPCClient()
        client._client = mock_client

        receipt = await client.get_transaction_receipt(endpoint, "0xabc")

        assert receipt == receipt_data
        call_args = mock_client.post.call_args
        assert call_args[1]["json"]["params"] == ["0xabc"]

    @pytest.mark.asyncio
    async def test_get_transaction_receipt_error(self):
        """Test getting transaction receipt with error."""
        endpoint = Endpoint(name="test", url="http://localhost:8545")

        mock_client = AsyncMock()
        request_error = httpx.RequestError("Connection refused", request=MagicMock())
        mock_client.post = AsyncMock(side_effect=request_error)

        client = RPCClient()
        client._client = mock_client

        receipt = await client.get_transaction_receipt(endpoint, "0xabc")

        assert receipt is None

    @pytest.mark.asyncio
    async def test_context_manager_exit_without_client(self):
        """Test __aexit__ when _client is already None."""
        client = RPCClient()
        # Exit without entering (client._client is None)
        await client.__aexit__(None, None, None)
        assert client._client is None
