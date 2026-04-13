"""Tests for normalization primitives."""

from __future__ import annotations

from json_rpc_scan.normalize import (
    ALWAYS_ON,
    apply_all,
    lowercase_hex,
    null_as_empty_bytes,
    sort_logs_by_index,
    strip_envelope,
)


class TestStripEnvelope:
    def test_removes_id(self):
        assert strip_envelope({"id": 42, "result": "0x1"}) == {"result": "0x1"}

    def test_removes_jsonrpc(self):
        assert strip_envelope({"jsonrpc": "2.0", "result": "0x1"}) == {"result": "0x1"}

    def test_removes_both(self):
        resp = {"jsonrpc": "2.0", "id": 7, "result": "0x1"}
        assert strip_envelope(resp) == {"result": "0x1"}

    def test_preserves_other_keys(self):
        resp = {"id": 1, "error": {"code": -1}}
        assert strip_envelope(resp) == {"error": {"code": -1}}

    def test_does_not_mutate_input(self):
        original = {"id": 1, "result": "0x1"}
        strip_envelope(original)
        assert "id" in original

    def test_empty_dict(self):
        assert strip_envelope({}) == {}


class TestLowercaseHex:
    def test_lowercases_address(self):
        resp = {"result": "0xAbCdEf0123456789AbCdEf0123456789AbCdEf01"}
        assert lowercase_hex(resp) == {
            "result": "0xabcdef0123456789abcdef0123456789abcdef01"
        }

    def test_recurses_into_dict(self):
        resp = {"result": {"from": "0xABCD", "to": "0xEF01"}}
        assert lowercase_hex(resp) == {"result": {"from": "0xabcd", "to": "0xef01"}}

    def test_recurses_into_list(self):
        resp = {"result": ["0xABCD", "0xEF01"]}
        assert lowercase_hex(resp) == {"result": ["0xabcd", "0xef01"]}

    def test_leaves_non_hex_strings_alone(self):
        resp = {"result": "Geth/v1.14.0", "method": "eth_call"}
        assert lowercase_hex(resp) == resp

    def test_leaves_non_hex_numbers_alone(self):
        resp = {"result": 42, "id": 7}
        assert lowercase_hex(resp) == resp

    def test_leaves_booleans_alone(self):
        assert lowercase_hex({"result": True}) == {"result": True}

    def test_leaves_none_alone(self):
        assert lowercase_hex({"result": None}) == {"result": None}

    def test_empty_hex(self):
        # "0x" is valid empty bytes and still matches the regex
        assert lowercase_hex({"result": "0x"}) == {"result": "0x"}

    def test_deeply_nested(self):
        resp = {
            "result": {
                "logs": [
                    {"topics": ["0xABCD", "0x1234"], "address": "0xDEADBEEF"},
                ],
            },
        }
        assert lowercase_hex(resp) == {
            "result": {
                "logs": [
                    {"topics": ["0xabcd", "0x1234"], "address": "0xdeadbeef"},
                ],
            },
        }


class TestSortLogsByIndex:
    def test_sorts_by_log_index_within_block(self):
        resp = {
            "result": [
                {"blockNumber": "0x1", "logIndex": "0x2", "data": "b"},
                {"blockNumber": "0x1", "logIndex": "0x0", "data": "a"},
                {"blockNumber": "0x1", "logIndex": "0x1", "data": "c"},
            ],
        }
        out = sort_logs_by_index(resp)
        assert [log["data"] for log in out["result"]] == ["a", "c", "b"]

    def test_sorts_across_blocks(self):
        resp = {
            "result": [
                {"blockNumber": "0x2", "logIndex": "0x0"},
                {"blockNumber": "0x1", "logIndex": "0x0"},
            ],
        }
        out = sort_logs_by_index(resp)
        assert [log["blockNumber"] for log in out["result"]] == ["0x1", "0x2"]

    def test_empty_list_unchanged(self):
        resp = {"result": []}
        assert sort_logs_by_index(resp) == resp

    def test_non_list_result_unchanged(self):
        resp = {"result": "0x1"}
        assert sort_logs_by_index(resp) == resp

    def test_missing_result_unchanged(self):
        resp = {"error": {"code": -1}}
        assert sort_logs_by_index(resp) == resp

    def test_list_of_non_dicts_unchanged(self):
        # Other methods may return list-of-strings results (e.g. tracer outputs)
        resp = {"result": ["0xabc", "0xdef"]}
        assert sort_logs_by_index(resp) == resp

    def test_missing_index_fields_defaults_to_zero(self):
        # Should not crash; all get sort key (0, 0) and preserve input order
        resp = {"result": [{"data": "x"}, {"data": "y"}]}
        out = sort_logs_by_index(resp)
        assert out["result"] == [{"data": "x"}, {"data": "y"}]


class TestNullAsEmptyBytes:
    def test_null_becomes_empty_bytes(self):
        assert null_as_empty_bytes({"result": None}) == {"result": "0x"}

    def test_empty_bytes_unchanged(self):
        assert null_as_empty_bytes({"result": "0x"}) == {"result": "0x"}

    def test_other_values_unchanged(self):
        assert null_as_empty_bytes({"result": "0x1234"}) == {"result": "0x1234"}

    def test_missing_result_unchanged(self):
        # Error responses have no `result` key at all
        assert null_as_empty_bytes({"error": {"code": -1}}) == {"error": {"code": -1}}


class TestApplyAll:
    def test_applies_in_order(self):
        resp = {"id": 1, "jsonrpc": "2.0", "result": "0xABCD"}
        out = apply_all(resp, [strip_envelope, lowercase_hex])
        assert out == {"result": "0xabcd"}

    def test_empty_list_is_identity(self):
        resp = {"id": 1, "result": "0xAB"}
        assert apply_all(resp, []) == resp


class TestAlwaysOn:
    def test_contains_strip_and_lowercase(self):
        assert strip_envelope in ALWAYS_ON
        assert lowercase_hex in ALWAYS_ON

    def test_composed_result(self):
        resp = {"id": 42, "jsonrpc": "2.0", "result": "0xABCD"}
        out = apply_all(resp, list(ALWAYS_ON))
        assert out == {"result": "0xabcd"}
