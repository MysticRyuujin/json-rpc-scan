"""Tests for ResponseComparator."""

from __future__ import annotations

from json_rpc_scan.comparator import ComparisonResult, ResponseComparator
from json_rpc_scan.normalize import null_as_empty_bytes, sort_logs_by_index


class TestAlwaysOnNormalization:
    def test_id_mismatch_is_not_a_diff(self):
        """JSON-RPC `id` differs between calls — never a real diff."""
        r1 = {"jsonrpc": "2.0", "id": 1, "result": "0x1"}
        r2 = {"jsonrpc": "2.0", "id": 2, "result": "0x1"}
        assert ResponseComparator().equal(r1, r2).equal

    def test_jsonrpc_version_mismatch_is_not_a_diff(self):
        r1 = {"jsonrpc": "2.0", "id": 1, "result": "0x1"}
        r2 = {"id": 1, "result": "0x1"}
        assert ResponseComparator().equal(r1, r2).equal

    def test_hex_case_mismatch_is_not_a_diff(self):
        """Nethermind returns EIP-55 checksummed addresses; Geth returns lowercase."""
        r1 = {"id": 1, "result": "0xAbCdEf01"}
        r2 = {"id": 1, "result": "0xabcdef01"}
        assert ResponseComparator().equal(r1, r2).equal

    def test_nested_hex_case_mismatch_is_not_a_diff(self):
        r1 = {"id": 1, "result": {"from": "0xABCD", "logs": [{"address": "0xDEAD"}]}}
        r2 = {"id": 1, "result": {"from": "0xabcd", "logs": [{"address": "0xdead"}]}}
        assert ResponseComparator().equal(r1, r2).equal

    def test_genuine_value_diff_is_reported(self):
        r1 = {"id": 1, "result": "0x1"}
        r2 = {"id": 1, "result": "0x2"}
        assert not ResponseComparator().equal(r1, r2).equal


class TestErrorHandling:
    def test_one_errored_is_always_a_diff(self):
        r1 = {"id": 1, "result": "0x1"}
        r2 = {"id": 1, "error": {"code": -32000, "message": "execution reverted"}}
        result = ResponseComparator().equal(r1, r2)
        assert not result.equal
        assert result.one_errored
        assert not result.both_errored

    def test_both_errored_same_message_is_equal(self):
        err = {"code": -32000, "message": "execution reverted"}
        r1 = {"id": 1, "error": err}
        r2 = {"id": 2, "error": err}
        result = ResponseComparator().equal(r1, r2)
        assert result.equal
        assert result.both_errored

    def test_both_errored_different_messages_is_diff(self):
        r1 = {"id": 1, "error": {"code": -32000, "message": "execution reverted"}}
        r2 = {"id": 1, "error": {"code": -32000, "message": "out of gas"}}
        result = ResponseComparator().equal(r1, r2)
        assert not result.equal
        assert result.both_errored
        assert not result.one_errored

    def test_two_success_responses_not_marked_errored(self):
        r1 = {"id": 1, "result": "0x1"}
        r2 = {"id": 1, "result": "0x1"}
        result = ResponseComparator().equal(r1, r2)
        assert result.equal
        assert not result.one_errored
        assert not result.both_errored


class TestOptInNormalizers:
    def test_log_order_without_normalizer_is_a_diff(self):
        r1 = {
            "id": 1,
            "result": [
                {"blockNumber": "0x1", "logIndex": "0x0", "data": "a"},
                {"blockNumber": "0x1", "logIndex": "0x1", "data": "b"},
            ],
        }
        r2 = {
            "id": 1,
            "result": [
                {"blockNumber": "0x1", "logIndex": "0x1", "data": "b"},
                {"blockNumber": "0x1", "logIndex": "0x0", "data": "a"},
            ],
        }
        assert not ResponseComparator().equal(r1, r2).equal

    def test_log_order_with_normalizer_is_not_a_diff(self):
        r1 = {
            "id": 1,
            "result": [
                {"blockNumber": "0x1", "logIndex": "0x0", "data": "a"},
                {"blockNumber": "0x1", "logIndex": "0x1", "data": "b"},
            ],
        }
        r2 = {
            "id": 1,
            "result": [
                {"blockNumber": "0x1", "logIndex": "0x1", "data": "b"},
                {"blockNumber": "0x1", "logIndex": "0x0", "data": "a"},
            ],
        }
        comparator = ResponseComparator(extra_normalizers=[sort_logs_by_index])
        assert comparator.equal(r1, r2).equal

    def test_null_vs_empty_bytes_without_normalizer_is_a_diff(self):
        r1 = {"id": 1, "result": None}
        r2 = {"id": 1, "result": "0x"}
        assert not ResponseComparator().equal(r1, r2).equal

    def test_null_vs_empty_bytes_with_normalizer_is_not_a_diff(self):
        r1 = {"id": 1, "result": None}
        r2 = {"id": 1, "result": "0x"}
        comparator = ResponseComparator(extra_normalizers=[null_as_empty_bytes])
        assert comparator.equal(r1, r2).equal


class TestNormalizedOutputPreserved:
    def test_result_exposes_normalized_responses(self):
        """Callers (DiffReporter) need the normalized dicts, not the originals."""
        r1 = {"jsonrpc": "2.0", "id": 1, "result": "0xABCD"}
        r2 = {"jsonrpc": "2.0", "id": 2, "result": "0x9999"}
        result = ResponseComparator().equal(r1, r2)
        # id / jsonrpc stripped, hex lowercased
        assert result.normalized1 == {"result": "0xabcd"}
        assert result.normalized2 == {"result": "0x9999"}

    def test_normalized_shows_both_errored_objects(self):
        r1 = {"id": 1, "error": {"code": -1, "message": "A"}}
        r2 = {"id": 2, "error": {"code": -2, "message": "B"}}
        result = ResponseComparator().equal(r1, r2)
        assert not result.equal
        assert result.normalized1 == {"error": {"code": -1, "message": "A"}}
        assert result.normalized2 == {"error": {"code": -2, "message": "B"}}


class TestComparisonResult:
    def test_default_flags_false(self):
        result = ComparisonResult(equal=True)
        assert not result.one_errored
        assert not result.both_errored
