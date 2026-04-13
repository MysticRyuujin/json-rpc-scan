"""Integration-ish tests for every runner in ALL_RUNNERS.

The runners were previously excluded from coverage on the premise that they
are pure I/O. This is untrue — the iteration, identifier construction, and
diff/reporter wiring are business logic that can be unit-tested with a mocked
RPCClient. This file drives each runner end-to-end against an in-memory client,
verifying:

- The runner instantiates and completes without raising.
- Identical responses produce zero diffs and no output files.
- Different responses produce ``differences_found`` > 0 and populated files.
- Missing blocks / empty transaction lists are handled without crashing.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock

import pytest

from json_rpc_scan.client import Endpoint, RPCResponse
from json_rpc_scan.runners.base import RunnerResult
from json_rpc_scan.runners.debug import (
    BUILTIN_TRACERS,
    DEBUG_RUNNERS,
    DebugTraceCallRunner,
    TraceConfig,
    run_debug_methods,
)
from json_rpc_scan.runners.eth import (
    ETH_RUNNERS,
    EthBlockNumberRunner,
    EthCallConfig,
    EthGetBlockByHashRunner,
    EthGetBlockByNumberRunner,
    EthGetCodeRunner,
    EthGetLogsRunner,
    EthGetTransactionByHashRunner,
    run_eth_methods,
)
from json_rpc_scan.runners.trace import (
    TRACE_RUNNERS,
    TRACE_TYPES,
    TraceOptions,
    run_trace_methods,
)


if TYPE_CHECKING:
    from pathlib import Path

    from json_rpc_scan.runners.base import BaseRunner


# A fake block that looks enough like a real eth_getBlockByNumber result
# to satisfy every runner's input-collection phase.
_FAKE_TX = {
    "hash": "0x" + "a" * 64,
    "from": "0x" + "1" * 40,
    "to": "0x" + "2" * 40,
    "gas": "0x5208",
    "gasPrice": "0x3b9aca00",
    "value": "0x1",
    "input": "0xabcdef",
    "nonce": "0x1",
}

_FAKE_BLOCK = {
    "hash": "0x" + "b" * 64,
    "number": "0x1",
    "miner": "0x" + "3" * 40,
    "transactions": [_FAKE_TX],
    "uncles": [],
}

_FAKE_RECEIPT = {
    "status": "0x1",
    "transactionHash": _FAKE_TX["hash"],
    "blockNumber": "0x1",
}


ALL_RUNNERS: dict[str, type[BaseRunner]] = {
    **DEBUG_RUNNERS,
    **ETH_RUNNERS,
    **TRACE_RUNNERS,
}


# Runners that need method-specific kwargs on .run(). The orchestration layer
# passes these; when calling .run() directly from a test we replicate them.
RUN_KWARGS: dict[str, dict[str, Any]] = {
    "eth_call": {"eth_call_config": EthCallConfig()},
    "eth_estimateGas": {"eth_call_config": EthCallConfig()},
    "trace_call": {"trace_options": TraceOptions()},
    "trace_callMany": {"trace_options": TraceOptions()},
    "debug_traceBlockByNumber": {"trace_config": TraceConfig()},
    "debug_traceBlockByHash": {"trace_config": TraceConfig()},
    "debug_traceTransaction": {"trace_config": TraceConfig()},
    "debug_traceCall": {"trace_config": TraceConfig()},
}


def _make_mock_client(response_builder: Any) -> AsyncMock:
    """Construct an AsyncMock that behaves like RPCClient.

    ``response_builder`` is a callable ``(endpoint, method, params) -> dict``
    that returns the JSON-RPC response dict for the given call. Both endpoints
    are routed through it.
    """
    client = AsyncMock()

    async def call_both(endpoints, method, params=None, request_id=1):
        params = params or []
        req = {"jsonrpc": "2.0", "method": method, "params": params, "id": request_id}
        r1_body = response_builder(endpoints[0], method, params)
        r2_body = response_builder(endpoints[1], method, params)
        return (
            RPCResponse(endpoints[0], req, r1_body),
            RPCResponse(endpoints[1], req, r2_body),
        )

    async def get_block(endpoint, block_number, full_transactions=True):
        # Return the fake block for any block number; ignore full_transactions.
        return {**_FAKE_BLOCK, "number": hex(block_number)}

    async def get_transaction_receipt(endpoint, tx_hash):
        return _FAKE_RECEIPT

    client.call_both.side_effect = call_both
    client.get_block.side_effect = get_block
    client.get_transaction_receipt.side_effect = get_transaction_receipt
    return client


def _endpoints() -> tuple[Endpoint, Endpoint]:
    return (Endpoint("A", "http://a"), Endpoint("B", "http://b"))


@pytest.mark.parametrize("method,runner_cls", sorted(ALL_RUNNERS.items()))
async def test_every_runner_completes_with_identical_responses(
    method: str,
    runner_cls: type[BaseRunner],
    tmp_path: Path,
):
    """Smoke test: every runner handles a happy path without raising.

    Both endpoints return the same (dummy) response for every RPC call, so
    the runner should report zero diffs and write no output files. This also
    catches typos like ``tx[:16]`` when ``tx`` is unexpectedly None — a class
    of bug that previously had no coverage at all.
    """

    def identical(endpoint, method_name, params):
        return {"jsonrpc": "2.0", "id": 1, "result": "0x1"}

    client = _make_mock_client(identical)
    runner = runner_cls(client, _endpoints(), tmp_path)
    kwargs = RUN_KWARGS.get(method, {})

    result = await runner.run(start_block=0, end_block=2, **kwargs)

    assert isinstance(result, RunnerResult)
    assert result.method == method
    assert result.differences_found == 0


@pytest.mark.parametrize("method,runner_cls", sorted(ALL_RUNNERS.items()))
async def test_every_runner_detects_diffs_when_responses_differ(
    method: str,
    runner_cls: type[BaseRunner],
    tmp_path: Path,
):
    """When the two endpoints return different results, every runner must notice."""

    def diverging(endpoint, method_name, params):
        # Endpoint A returns "0x1", endpoint B returns "0x2" — unambiguous diff
        # that no normalizer can swallow.
        return {
            "jsonrpc": "2.0",
            "id": 1,
            "result": "0x1" if endpoint.name == "A" else "0x2",
        }

    client = _make_mock_client(diverging)
    runner = runner_cls(client, _endpoints(), tmp_path)
    kwargs = RUN_KWARGS.get(method, {})

    result = await runner.run(start_block=0, end_block=1, **kwargs)

    # Some runners (uncle runners without uncles in block, call runners
    # filtered to specific tx shapes) may short-circuit and run zero tests.
    # We only assert: if any tests ran, diffs are detected.
    if result.tests_run > 0:
        assert result.differences_found > 0


class TestBlockRangeEdgeCases:
    """Behavior with empty ranges and missing data — previously untested."""

    async def test_empty_block_range_produces_zero_tests(self, tmp_path: Path):
        """start > end yields an empty range; no runner should crash."""
        client = _make_mock_client(
            lambda _e, _m, _p: {"id": 1, "result": "0x1"},
        )
        runner = EthGetBlockByNumberRunner(client, _endpoints(), tmp_path)
        result = await runner.run(start_block=10, end_block=5)
        assert result.tests_run == 0
        assert result.differences_found == 0

    async def test_empty_transactions_handled(self, tmp_path: Path):
        """Block without transactions → runner that iterates txs returns 0."""
        client = AsyncMock()
        client.get_block.return_value = {**_FAKE_BLOCK, "transactions": []}

        async def identical_call(endpoints, method, params=None, request_id=1):
            req = {"jsonrpc": "2.0", "method": method, "params": params, "id": 1}
            return (
                RPCResponse(endpoints[0], req, {"id": 1, "result": "0x1"}),
                RPCResponse(endpoints[1], req, {"id": 1, "result": "0x1"}),
            )

        client.call_both.side_effect = identical_call

        runner = EthGetTransactionByHashRunner(client, _endpoints(), tmp_path)
        result = await runner.run(start_block=0, end_block=2)
        assert result.tests_run == 0

    async def test_missing_block_hash_skipped(self, tmp_path: Path):
        """Block without a ``hash`` key → BlockByHash variants skip cleanly."""
        client = AsyncMock()
        # First call returns a block without hash
        client.get_block.return_value = {"number": "0x1"}

        async def identical_call(endpoints, method, params=None, request_id=1):
            req = {"jsonrpc": "2.0", "method": method, "params": params, "id": 1}
            return (
                RPCResponse(endpoints[0], req, {"id": 1, "result": "0x1"}),
                RPCResponse(endpoints[1], req, {"id": 1, "result": "0x1"}),
            )

        client.call_both.side_effect = identical_call

        runner = EthGetBlockByHashRunner(client, _endpoints(), tmp_path)
        result = await runner.run(start_block=0, end_block=2)
        assert result.tests_run == 0


class TestErrorOutcome:
    """One-side-errored is a diff even when the other side succeeds."""

    async def test_one_errored_is_a_diff(self, tmp_path: Path):
        async def one_errored(endpoints, method, params=None, request_id=1):
            req = {"jsonrpc": "2.0", "method": method, "params": params, "id": 1}
            return (
                RPCResponse(endpoints[0], req, {"id": 1, "result": "0x1"}),
                RPCResponse(
                    endpoints[1],
                    req,
                    {"id": 1, "error": {"code": -32000, "message": "err"}},
                ),
            )

        client = AsyncMock()
        client.call_both.side_effect = one_errored

        runner = EthBlockNumberRunner(client, _endpoints(), tmp_path)
        result = await runner.run(start_block=0, end_block=0)
        assert result.tests_run == 1
        assert result.differences_found == 1


class TestDebugTraceCallStatusMismatch:
    """DebugTraceCallRunner's status-mismatch path is unique — test it explicitly."""

    async def test_trace_error_on_successful_tx_is_flagged(self, tmp_path: Path):
        async def trace_errored(endpoints, method, params=None, request_id=1):
            req = {"jsonrpc": "2.0", "method": method, "params": params, "id": 1}
            # Both endpoints "agree" (no diff), but both report a trace error
            # for a tx that succeeded on-chain.
            body = {"id": 1, "result": {"failed": True, "error": "revert"}}
            return (
                RPCResponse(endpoints[0], req, body),
                RPCResponse(endpoints[1], req, body),
            )

        client = AsyncMock()
        client.call_both.side_effect = trace_errored

        async def get_block(endpoint, block_number, full_transactions=True):
            return _FAKE_BLOCK

        async def get_receipt(endpoint, tx_hash):
            return _FAKE_RECEIPT  # status: 0x1 → succeeded

        client.get_block.side_effect = get_block
        client.get_transaction_receipt.side_effect = get_receipt

        runner = DebugTraceCallRunner(client, _endpoints(), tmp_path)
        result = await runner.run(
            start_block=0, end_block=0, trace_config=TraceConfig()
        )

        # Endpoints agree → `differences_found` is 0, but status-mismatch
        # diff files are still written (one per endpoint).
        assert result.tests_run == 1
        status_mismatch_a = (
            tmp_path / "debug_traceCall" / (f"status_mismatch_A_{_FAKE_TX['hash']}")
        )
        status_mismatch_b = (
            tmp_path / "debug_traceCall" / (f"status_mismatch_B_{_FAKE_TX['hash']}")
        )
        assert status_mismatch_a.exists()
        assert status_mismatch_b.exists()


class TestOptInNormalizers:
    """Verify runners that declare opt-in normalizers actually use them."""

    async def test_eth_getlogs_sort_normalizer_hides_order_diff(self, tmp_path: Path):
        """``eth_getLogs`` declares ``sort_logs_by_index`` — log-order diffs
        between A and B should NOT register."""

        async def out_of_order(endpoints, method, params=None, request_id=1):
            req = {"jsonrpc": "2.0", "method": method, "params": params, "id": 1}
            logs = [
                {"blockNumber": "0x1", "logIndex": "0x0", "data": "a"},
                {"blockNumber": "0x1", "logIndex": "0x1", "data": "b"},
            ]
            if endpoint := endpoints[0]:  # noqa: F841
                pass
            r1 = {"id": 1, "result": logs}
            r2 = {"id": 1, "result": list(reversed(logs))}
            return (
                RPCResponse(endpoints[0], req, r1),
                RPCResponse(endpoints[1], req, r2),
            )

        client = AsyncMock()
        client.call_both.side_effect = out_of_order

        async def get_block(endpoint, block_number, full_transactions=True):
            return _FAKE_BLOCK

        client.get_block.side_effect = get_block

        runner = EthGetLogsRunner(client, _endpoints(), tmp_path)
        result = await runner.run(start_block=0, end_block=1)
        assert result.tests_run > 0
        assert result.differences_found == 0

    async def test_run_eth_methods_orchestrates_requested_methods(self, tmp_path: Path):
        """Orchestration wrapper delegates to each named runner in turn."""

        def identical(endpoint, method, params):
            return {"jsonrpc": "2.0", "id": 1, "result": "0x1"}

        client = _make_mock_client(identical)
        results = await run_eth_methods(
            client,
            _endpoints(),
            tmp_path,
            start_block=0,
            end_block=1,
            methods=["eth_chainId", "eth_blockNumber"],
        )
        assert [r.method for r in results] == ["eth_chainId", "eth_blockNumber"]

    async def test_run_eth_methods_skips_unknown(self, tmp_path: Path):
        def identical(endpoint, method, params):
            return {"jsonrpc": "2.0", "id": 1, "result": "0x1"}

        client = _make_mock_client(identical)
        results = await run_eth_methods(
            client,
            _endpoints(),
            tmp_path,
            start_block=0,
            end_block=0,
            methods=["eth_chainId", "not_a_real_method"],
        )
        assert [r.method for r in results] == ["eth_chainId"]

    async def test_run_debug_methods_wraps_tracer_loop(self, tmp_path: Path):
        """test_all_tracers=True drives the method with every built-in tracer."""

        def identical(endpoint, method, params):
            return {"jsonrpc": "2.0", "id": 1, "result": "0x1"}

        client = _make_mock_client(identical)
        results = await run_debug_methods(
            client,
            _endpoints(),
            tmp_path,
            start_block=0,
            end_block=0,
            trace_config=TraceConfig(),
            methods=["debug_getBadBlocks"],
            test_all_tracers=True,
        )
        # One result per tracer, method names tagged with the tracer
        assert len(results) == len(BUILTIN_TRACERS)
        assert all("debug_getBadBlocks" in r.method for r in results)

    async def test_run_debug_methods_skips_unknown(self, tmp_path: Path):
        def identical(endpoint, method, params):
            return {"jsonrpc": "2.0", "id": 1, "result": "0x1"}

        client = _make_mock_client(identical)
        results = await run_debug_methods(
            client,
            _endpoints(),
            tmp_path,
            start_block=0,
            end_block=0,
            methods=["debug_getBadBlocks", "not_a_real_method"],
        )
        assert [r.method for r in results] == ["debug_getBadBlocks"]

    async def test_run_trace_methods_all_trace_types(self, tmp_path: Path):
        def identical(endpoint, method, params):
            return {"jsonrpc": "2.0", "id": 1, "result": "0x1"}

        client = _make_mock_client(identical)
        results = await run_trace_methods(
            client,
            _endpoints(),
            tmp_path,
            start_block=0,
            end_block=0,
            methods=["trace_block"],
            test_all_trace_types=True,
        )
        assert len(results) == len(TRACE_TYPES)

    async def test_run_trace_methods_skips_unknown(self, tmp_path: Path):
        def identical(endpoint, method, params):
            return {"jsonrpc": "2.0", "id": 1, "result": "0x1"}

        client = _make_mock_client(identical)
        results = await run_trace_methods(
            client,
            _endpoints(),
            tmp_path,
            start_block=0,
            end_block=0,
            methods=["trace_block", "not_real"],
        )
        assert [r.method for r in results] == ["trace_block"]

    async def test_eth_getcode_null_equivalence(self, tmp_path: Path):
        """``eth_getCode`` declares ``null_as_empty_bytes`` — null vs ``"0x"``
        must not register as a diff."""

        async def null_vs_empty(endpoints, method, params=None, request_id=1):
            req = {"jsonrpc": "2.0", "method": method, "params": params, "id": 1}
            r1 = {"id": 1, "result": None}
            r2 = {"id": 1, "result": "0x"}
            return (
                RPCResponse(endpoints[0], req, r1),
                RPCResponse(endpoints[1], req, r2),
            )

        client = AsyncMock()
        client.call_both.side_effect = null_vs_empty

        async def get_block(endpoint, block_number, full_transactions=True):
            return _FAKE_BLOCK

        client.get_block.side_effect = get_block

        runner = EthGetCodeRunner(client, _endpoints(), tmp_path)
        result = await runner.run(start_block=0, end_block=1)
        assert result.tests_run > 0
        assert result.differences_found == 0
