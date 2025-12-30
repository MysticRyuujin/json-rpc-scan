"""Tests for the client module."""

from __future__ import annotations

from json_rpc_scan.client import Endpoint, RPCResponse


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
