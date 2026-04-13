"""Tests for BaseRunner helpers: compare_one, compare_over, tx_to_call_obj."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar
from unittest.mock import AsyncMock

from json_rpc_scan.client import Endpoint, RPCResponse
from json_rpc_scan.normalize import Normalizer, sort_logs_by_index
from json_rpc_scan.runners.base import BaseRunner, RunnerResult, tx_to_call_obj


if TYPE_CHECKING:
    from pathlib import Path


class StubRunner(BaseRunner):
    """Concrete subclass so we can exercise the base-class methods."""

    method_name = "test_method"
    description = "stub for tests"

    async def run(
        self,
        start_block: int,  # noqa: ARG002
        end_block: int,  # noqa: ARG002
        **kwargs: Any,  # noqa: ARG002
    ) -> RunnerResult:  # pragma: no cover — not exercised
        return RunnerResult(self.method_name, 0, 0)


class StubRunnerWithNormalizer(StubRunner):
    """Runner that declares an opt-in normalizer."""

    extra_normalizers: ClassVar[list[Normalizer]] = [sort_logs_by_index]


def _make_runner(
    tmp_path: Path,
    *,
    cls: type[BaseRunner] = StubRunner,
) -> tuple[StubRunner, AsyncMock]:
    client = AsyncMock()
    endpoints = (Endpoint("A", "http://a"), Endpoint("B", "http://b"))
    runner = cls(client, endpoints, tmp_path)
    return runner, client  # type: ignore[return-value]


def _resp(endpoint: Endpoint, payload: dict[str, Any]) -> RPCResponse:
    return RPCResponse(
        endpoint=endpoint,
        request={"jsonrpc": "2.0", "method": "test_method", "params": [], "id": 1},
        response=payload,
    )


class TestCompareOneEqual:
    async def test_equal_responses_return_false(self, tmp_path):
        runner, client = _make_runner(tmp_path)
        resp = {"jsonrpc": "2.0", "id": 1, "result": "0x1"}
        client.call_both.return_value = (
            _resp(runner.endpoints[0], resp),
            _resp(runner.endpoints[1], resp),
        )
        is_diff = await runner.compare_one("block_1", [hex(1)])
        assert is_diff is False

    async def test_equal_responses_do_not_write_files(self, tmp_path):
        runner, client = _make_runner(tmp_path)
        resp = {"jsonrpc": "2.0", "id": 1, "result": "0x1"}
        client.call_both.return_value = (
            _resp(runner.endpoints[0], resp),
            _resp(runner.endpoints[1], resp),
        )
        await runner.compare_one("block_1", [hex(1)])
        assert not any(tmp_path.iterdir())

    async def test_id_difference_does_not_register_as_diff(self, tmp_path):
        """Always-on normalizer strips id — different ids must not trigger save_diff."""
        runner, client = _make_runner(tmp_path)
        r1 = {"jsonrpc": "2.0", "id": 1, "result": "0x1"}
        r2 = {"jsonrpc": "2.0", "id": 999, "result": "0x1"}
        client.call_both.return_value = (
            _resp(runner.endpoints[0], r1),
            _resp(runner.endpoints[1], r2),
        )
        assert await runner.compare_one("block_1", [hex(1)]) is False

    async def test_hex_case_difference_does_not_register_as_diff(self, tmp_path):
        runner, client = _make_runner(tmp_path)
        r1 = {"id": 1, "result": "0xABCD"}
        r2 = {"id": 1, "result": "0xabcd"}
        client.call_both.return_value = (
            _resp(runner.endpoints[0], r1),
            _resp(runner.endpoints[1], r2),
        )
        assert await runner.compare_one("block_1", [hex(1)]) is False


class TestCompareOneDiff:
    async def test_value_diff_returns_true(self, tmp_path):
        runner, client = _make_runner(tmp_path)
        r1 = {"id": 1, "result": "0x1"}
        r2 = {"id": 1, "result": "0x2"}
        client.call_both.return_value = (
            _resp(runner.endpoints[0], r1),
            _resp(runner.endpoints[1], r2),
        )
        assert await runner.compare_one("block_1", [hex(1)]) is True

    async def test_value_diff_writes_files(self, tmp_path):
        runner, client = _make_runner(tmp_path)
        r1 = {"id": 1, "result": "0x1"}
        r2 = {"id": 1, "result": "0x2"}
        client.call_both.return_value = (
            _resp(runner.endpoints[0], r1),
            _resp(runner.endpoints[1], r2),
        )
        await runner.compare_one("block_1", [hex(1)])
        diff_dir = tmp_path / "test_method" / "block_1"
        assert diff_dir.exists()
        assert (diff_dir / "request.json").exists()
        assert (diff_dir / "A_response.json").exists()
        assert (diff_dir / "B_response.json").exists()

    async def test_saved_responses_are_normalized(self, tmp_path):
        """Diff files should contain the post-normalization dicts."""
        runner, client = _make_runner(tmp_path)
        r1 = {"jsonrpc": "2.0", "id": 1, "result": "0xAA"}
        r2 = {"jsonrpc": "2.0", "id": 1, "result": "0xBB"}
        client.call_both.return_value = (
            _resp(runner.endpoints[0], r1),
            _resp(runner.endpoints[1], r2),
        )
        await runner.compare_one("block_1", [hex(1)])
        saved_a = (tmp_path / "test_method" / "block_1" / "A_response.json").read_text()
        # id / jsonrpc stripped, hex lowercased
        assert '"id"' not in saved_a
        assert '"jsonrpc"' not in saved_a
        assert "0xaa" in saved_a


class TestTransportErrorHandling:
    """Regression (QA): both endpoints unreachable must surface as a diff.

    Previously RPCClient returned `response={}` on network failure, and two
    empty dicts compared equal via envelope-stripping — so a run against two
    dead endpoints silently reported "0 diffs, exit 0". The fix folds
    transport errors into response["error"] so the comparator treats them
    like JSON-RPC errors.
    """

    async def test_both_endpoints_transport_errored_is_always_a_diff(self, tmp_path):
        """Both sides unreachable with the same network error → always a diff.

        Transport failures are infrastructure problems, not valid RPC
        comparisons. Even if both endpoints return an identical
        "connection refused", the run should register that as a diff so
        the user sees the infra problem instead of a misleading "0 diffs".
        """
        runner, client = _make_runner(tmp_path)
        err = {
            "error": {
                "code": -32603,
                "message": "Connection refused",
                "transport": True,
            }
        }
        client.call_both.return_value = (
            _resp(runner.endpoints[0], err),
            _resp(runner.endpoints[1], err),
        )
        assert await runner.compare_one("test", []) is True

    async def test_both_endpoints_errored_differently_is_diff(self, tmp_path):
        runner, client = _make_runner(tmp_path)
        r1 = {
            "error": {
                "code": -32603,
                "message": "Connection refused",
                "transport": True,
            }
        }
        r2 = {"error": {"code": -32603, "message": "Timeout", "transport": True}}
        client.call_both.return_value = (
            _resp(runner.endpoints[0], r1),
            _resp(runner.endpoints[1], r2),
        )
        assert await runner.compare_one("test", []) is True


class TestCompareOneErrors:
    async def test_one_side_errored_is_a_diff(self, tmp_path):
        runner, client = _make_runner(tmp_path)
        r1 = {"id": 1, "result": "0x1"}
        r2 = {"id": 1, "error": {"code": -32000, "message": "reverted"}}
        client.call_both.return_value = (
            _resp(runner.endpoints[0], r1),
            _resp(runner.endpoints[1], r2),
        )
        assert await runner.compare_one("call_xyz", []) is True

    async def test_both_same_error_is_not_a_diff(self, tmp_path):
        """Regression: empty-body responses with identical errors must not diff.

        Previously `resp1.response != resp2.response` compared empty dicts
        from two different 500s as equal — which it still does semantically,
        but only when the error objects are *actually* the same.
        """
        runner, client = _make_runner(tmp_path)
        err = {"code": -32000, "message": "err"}
        r1 = {"id": 1, "error": err}
        r2 = {"id": 2, "error": err}
        client.call_both.return_value = (
            _resp(runner.endpoints[0], r1),
            _resp(runner.endpoints[1], r2),
        )
        assert await runner.compare_one("call_xyz", []) is False

    async def test_different_errors_is_a_diff(self, tmp_path):
        runner, client = _make_runner(tmp_path)
        r1 = {"id": 1, "error": {"code": -1, "message": "A"}}
        r2 = {"id": 1, "error": {"code": -2, "message": "B"}}
        client.call_both.return_value = (
            _resp(runner.endpoints[0], r1),
            _resp(runner.endpoints[1], r2),
        )
        assert await runner.compare_one("call_xyz", []) is True


class TestCompareOver:
    async def test_counts_all_tests_as_run(self, tmp_path):
        runner, client = _make_runner(tmp_path)
        resp = {"id": 1, "result": "0x1"}
        client.call_both.return_value = (
            _resp(runner.endpoints[0], resp),
            _resp(runner.endpoints[1], resp),
        )
        inputs = [(f"block_{n}", [hex(n)]) for n in range(5)]
        result = await runner.compare_over(inputs, total=5)
        assert result.tests_run == 5
        assert result.differences_found == 0

    async def test_counts_diffs(self, tmp_path):
        runner, client = _make_runner(tmp_path)

        # Endpoint B returns different results than A for every call
        async def call_both(endpoints, method, params):
            req = {"jsonrpc": "2.0", "method": method, "params": params, "id": 1}
            return (
                RPCResponse(endpoints[0], req, {"id": 1, "result": "0x1"}),
                RPCResponse(endpoints[1], req, {"id": 1, "result": "0x2"}),
            )

        client.call_both.side_effect = call_both
        inputs = [(f"block_{n}", [hex(n)]) for n in range(3)]
        result = await runner.compare_over(inputs, total=3)
        assert result.tests_run == 3
        assert result.differences_found == 3

    async def test_empty_input_produces_zero_stats(self, tmp_path):
        runner, _client = _make_runner(tmp_path)
        result = await runner.compare_over([], total=0)
        assert result.tests_run == 0
        assert result.differences_found == 0

    async def test_method_name_in_result(self, tmp_path):
        runner, _client = _make_runner(tmp_path)
        result = await runner.compare_over([], total=0)
        assert result.method == "test_method"


class TestOptInNormalizers:
    async def test_log_order_diff_swallowed_by_declared_normalizer(self, tmp_path):
        runner, client = _make_runner(tmp_path, cls=StubRunnerWithNormalizer)
        r1 = {
            "id": 1,
            "result": [
                {"blockNumber": "0x1", "logIndex": "0x0"},
                {"blockNumber": "0x1", "logIndex": "0x1"},
            ],
        }
        r2 = {
            "id": 1,
            "result": [
                {"blockNumber": "0x1", "logIndex": "0x1"},
                {"blockNumber": "0x1", "logIndex": "0x0"},
            ],
        }
        client.call_both.return_value = (
            _resp(runner.endpoints[0], r1),
            _resp(runner.endpoints[1], r2),
        )
        assert await runner.compare_one("logs", [{}]) is False


class TestTxToCallObj:
    def test_basic_fields(self):
        tx = {"from": "0xA", "to": "0xB", "gas": "0x1", "value": "0x2"}
        assert tx_to_call_obj(tx) == {
            "from": "0xA",
            "to": "0xB",
            "gas": "0x1",
            "value": "0x2",
        }

    def test_maps_input_to_data(self):
        tx = {"from": "0xA", "to": "0xB", "input": "0xdeadbeef"}
        assert tx_to_call_obj(tx)["data"] == "0xdeadbeef"

    def test_eip1559_gas_pricing(self):
        tx = {
            "from": "0xA",
            "to": "0xB",
            "maxFeePerGas": "0x10",
            "maxPriorityFeePerGas": "0x1",
        }
        call = tx_to_call_obj(tx)
        assert call["maxFeePerGas"] == "0x10"
        assert call["maxPriorityFeePerGas"] == "0x1"
        assert "gasPrice" not in call

    def test_legacy_gas_pricing(self):
        tx = {"from": "0xA", "to": "0xB", "gasPrice": "0x100"}
        call = tx_to_call_obj(tx)
        assert call["gasPrice"] == "0x100"
        assert "maxFeePerGas" not in call

    def test_eip1559_takes_precedence(self):
        tx = {"maxFeePerGas": "0x10", "gasPrice": "0x5"}
        call = tx_to_call_obj(tx)
        assert "maxFeePerGas" in call
        assert "gasPrice" not in call

    def test_access_list_included(self):
        tx = {"from": "0xA", "accessList": [{"address": "0xB", "storageKeys": []}]}
        assert tx_to_call_obj(tx)["accessList"] == [
            {"address": "0xB", "storageKeys": []}
        ]

    def test_include_gas_false_drops_gas(self):
        tx = {"from": "0xA", "to": "0xB", "gas": "0x1", "value": "0x2"}
        call = tx_to_call_obj(tx, include_gas=False)
        assert "gas" not in call
        assert call["from"] == "0xA"

    def test_include_gas_pricing_false_drops_fees(self):
        tx = {"from": "0xA", "maxFeePerGas": "0x10", "gasPrice": "0x5"}
        call = tx_to_call_obj(tx, include_gas_pricing=False)
        assert "maxFeePerGas" not in call
        assert "gasPrice" not in call

    def test_include_access_list_false_drops_access_list(self):
        tx = {"from": "0xA", "accessList": [{"address": "0xB", "storageKeys": []}]}
        call = tx_to_call_obj(tx, include_access_list=False)
        assert "accessList" not in call

    def test_skips_missing_fields(self):
        tx = {"to": "0xB"}  # no from, gas, value
        call = tx_to_call_obj(tx)
        assert call == {"to": "0xB"}

    def test_estimategas_preset(self):
        """eth_estimateGas uses no gas/gas-pricing/access-list."""
        tx = {
            "from": "0xA",
            "to": "0xB",
            "gas": "0x1",
            "value": "0x2",
            "input": "0xdead",
            "maxFeePerGas": "0x10",
            "accessList": [{"address": "0xC"}],
        }
        call = tx_to_call_obj(
            tx,
            include_gas=False,
            include_gas_pricing=False,
            include_access_list=False,
        )
        assert call == {
            "from": "0xA",
            "to": "0xB",
            "value": "0x2",
            "data": "0xdead",
        }


class TestRunnerConstruction:
    def test_comparator_created_with_opt_in_normalizers(self, tmp_path):
        runner, _ = _make_runner(tmp_path, cls=StubRunnerWithNormalizer)
        # Internal detail but worth pinning: subclass normalizers reach comparator.
        assert sort_logs_by_index in runner.comparator._normalizers

    def test_default_runner_only_has_always_on_normalizers(self, tmp_path):
        runner, _ = _make_runner(tmp_path)
        # Only strip_envelope + lowercase_hex
        assert len(runner.comparator._normalizers) == 2
