"""Tests for the diff module."""

from __future__ import annotations

import pytest

from json_rpc_scan.diff import DiffComputer, Difference


class TestDiffComputer:
    """Tests for DiffComputer class."""

    @pytest.fixture
    def computer(self) -> DiffComputer:
        """Create a DiffComputer instance."""
        return DiffComputer()

    def test_identical_responses(self, computer: DiffComputer):
        """Test that identical responses produce no differences."""
        resp1 = {"jsonrpc": "2.0", "id": 1, "result": {"foo": "bar"}}
        resp2 = {"jsonrpc": "2.0", "id": 1, "result": {"foo": "bar"}}

        diffs = computer.compute(resp1, resp2)
        assert len(diffs) == 0

    def test_value_changed(self, computer: DiffComputer):
        """Test detection of changed values."""
        resp1 = {"jsonrpc": "2.0", "id": 1, "result": {"value": "0x100"}}
        resp2 = {"jsonrpc": "2.0", "id": 1, "result": {"value": "0x200"}}

        diffs = computer.compute(resp1, resp2)
        assert len(diffs) == 1
        assert diffs[0].diff_type == "value_changed"
        assert diffs[0].path == "result.value"
        assert diffs[0].value1 == "0x100"
        assert diffs[0].value2 == "0x200"

    def test_missing_field(self, computer: DiffComputer):
        """Test detection of missing fields."""
        resp1 = {"jsonrpc": "2.0", "id": 1, "result": {"a": 1, "b": 2}}
        resp2 = {"jsonrpc": "2.0", "id": 1, "result": {"a": 1}}

        diffs = computer.compute(resp1, resp2)
        assert len(diffs) == 1
        assert diffs[0].diff_type == "missing_in_endpoint2"
        assert diffs[0].path == "result.b"

    def test_added_field(self, computer: DiffComputer):
        """Test detection of added fields."""
        resp1 = {"jsonrpc": "2.0", "id": 1, "result": {"a": 1}}
        resp2 = {"jsonrpc": "2.0", "id": 1, "result": {"a": 1, "b": 2}}

        diffs = computer.compute(resp1, resp2)
        assert len(diffs) == 1
        assert diffs[0].diff_type == "added_in_endpoint2"
        assert diffs[0].path == "result.b"

    def test_type_mismatch(self, computer: DiffComputer):
        """Test detection of type mismatches."""
        resp1 = {"jsonrpc": "2.0", "id": 1, "result": {"value": "string"}}
        resp2 = {"jsonrpc": "2.0", "id": 1, "result": {"value": 123}}

        diffs = computer.compute(resp1, resp2)
        assert len(diffs) == 1
        assert diffs[0].diff_type == "type_mismatch"
        assert diffs[0].extra["type1"] == "str"
        assert diffs[0].extra["type2"] == "int"

    def test_list_length_mismatch(self, computer: DiffComputer):
        """Test detection of list length mismatches."""
        resp1 = {"jsonrpc": "2.0", "id": 1, "result": [1, 2, 3]}
        resp2 = {"jsonrpc": "2.0", "id": 1, "result": [1, 2]}

        diffs = computer.compute(resp1, resp2)
        # Should report length mismatch
        length_diffs = [d for d in diffs if d.diff_type == "length_mismatch"]
        assert len(length_diffs) == 1
        assert length_diffs[0].extra["length1"] == 3
        assert length_diffs[0].extra["length2"] == 2

    def test_error_vs_success(self, computer: DiffComputer):
        """Test detection of error vs success response."""
        resp1 = {
            "jsonrpc": "2.0",
            "id": 1,
            "error": {"code": -32600, "message": "fail"},
        }
        resp2 = {"jsonrpc": "2.0", "id": 1, "result": "ok"}

        diffs = computer.compute(resp1, resp2)
        assert len(diffs) == 1
        assert diffs[0].diff_type == "error_vs_success"

    def test_success_vs_error(self, computer: DiffComputer):
        """Test detection of success vs error response."""
        resp1 = {"jsonrpc": "2.0", "id": 1, "result": "ok"}
        resp2 = {
            "jsonrpc": "2.0",
            "id": 1,
            "error": {"code": -32600, "message": "fail"},
        }

        diffs = computer.compute(resp1, resp2)
        assert len(diffs) == 1
        assert diffs[0].diff_type == "success_vs_error"

    def test_both_errors_same_message(self, computer: DiffComputer):
        """Test that identical errors produce no differences."""
        error = {"code": -32600, "message": "fail"}
        resp1 = {"jsonrpc": "2.0", "id": 1, "error": error}
        resp2 = {"jsonrpc": "2.0", "id": 1, "error": error}

        diffs = computer.compute(resp1, resp2)
        assert len(diffs) == 0

    def test_both_errors_different_message(self, computer: DiffComputer):
        """Test detection of different error messages."""
        resp1 = {
            "jsonrpc": "2.0",
            "id": 1,
            "error": {"code": -32600, "message": "fail1"},
        }
        resp2 = {
            "jsonrpc": "2.0",
            "id": 1,
            "error": {"code": -32600, "message": "fail2"},
        }

        diffs = computer.compute(resp1, resp2)
        assert len(diffs) == 1
        assert diffs[0].diff_type == "error_message_differs"

    def test_nested_dict_difference(self, computer: DiffComputer):
        """Test detection of nested dictionary differences."""
        resp1 = {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {"outer": {"inner": {"deep": "value1"}}},
        }
        resp2 = {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {"outer": {"inner": {"deep": "value2"}}},
        }

        diffs = computer.compute(resp1, resp2)
        assert len(diffs) == 1
        assert diffs[0].path == "result.outer.inner.deep"
        assert diffs[0].diff_type == "value_changed"


class TestDifference:
    """Tests for Difference dataclass."""

    def test_difference_creation(self):
        """Test creating a Difference object."""
        diff = Difference(
            path="result.value",
            diff_type="value_changed",
            value1="old",
            value2="new",
        )

        assert diff.path == "result.value"
        assert diff.diff_type == "value_changed"
        assert diff.value1 == "old"
        assert diff.value2 == "new"
        assert diff.extra == {}

    def test_difference_with_extra(self):
        """Test Difference with extra metadata."""
        diff = Difference(
            path="result.value",
            diff_type="type_mismatch",
            value1="str",
            value2=123,
            extra={"type1": "str", "type2": "int"},
        )

        assert diff.extra["type1"] == "str"
        assert diff.extra["type2"] == "int"
