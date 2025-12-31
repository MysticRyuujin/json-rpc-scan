"""Tests for the diff module."""

from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from json_rpc_scan.diff import DiffComputer, DiffReporter, Difference


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

    def test_list_item_difference(self, computer: DiffComputer):
        """Test detection of differences in list items."""
        resp1 = {"jsonrpc": "2.0", "id": 1, "result": [1, 2, 3]}
        resp2 = {"jsonrpc": "2.0", "id": 1, "result": [1, 5, 3]}

        diffs = computer.compute(resp1, resp2)
        assert len(diffs) == 1
        assert diffs[0].path == "result[1]"
        assert diffs[0].diff_type == "value_changed"

    def test_error_in_result_dict(self, computer: DiffComputer):
        """Test detection of error in result dict."""
        resp1 = {"jsonrpc": "2.0", "id": 1, "result": {"error": "fail"}}
        resp2 = {"jsonrpc": "2.0", "id": 1, "result": {"success": True}}

        diffs = computer.compute(resp1, resp2)
        assert len(diffs) == 1
        assert diffs[0].diff_type == "error_vs_success"

    def test_error_message_extraction_string(self, computer: DiffComputer):
        """Test error message extraction when error is a string."""
        resp = {"jsonrpc": "2.0", "id": 1, "error": "Simple error"}
        assert computer._get_error_message(resp) == "Simple error"

    def test_error_message_extraction_dict(self, computer: DiffComputer):
        """Test error message extraction when error is a dict."""
        resp = {"jsonrpc": "2.0", "id": 1, "error": {"code": -1, "message": "Error msg"}}
        assert computer._get_error_message(resp) == "Error msg"

    def test_error_message_extraction_dict_no_message(self, computer: DiffComputer):
        """Test error message extraction when error dict has no message."""
        resp = {"jsonrpc": "2.0", "id": 1, "error": {"code": -1}}
        assert computer._get_error_message(resp) == "{'code': -1}"

    def test_error_message_unknown_format(self, computer: DiffComputer):
        """Test error message extraction with unexpected format."""
        # Response with result dict but no error field, and no top-level error
        resp = {"jsonrpc": "2.0", "id": 1, "result": {"data": "something"}}
        assert computer._get_error_message(resp) == "Unknown error"

    def test_empty_dicts(self, computer: DiffComputer):
        """Test comparison of empty dicts."""
        resp1 = {"jsonrpc": "2.0", "id": 1, "result": {}}
        resp2 = {"jsonrpc": "2.0", "id": 1, "result": {}}

        diffs = computer.compute(resp1, resp2)
        assert len(diffs) == 0

    def test_empty_lists(self, computer: DiffComputer):
        """Test comparison of empty lists."""
        resp1 = {"jsonrpc": "2.0", "id": 1, "result": []}
        resp2 = {"jsonrpc": "2.0", "id": 1, "result": []}

        diffs = computer.compute(resp1, resp2)
        assert len(diffs) == 0

    def test_list_with_different_types(self, computer: DiffComputer):
        """Test list comparison with different types."""
        resp1 = {"jsonrpc": "2.0", "id": 1, "result": [1, 2, 3]}
        resp2 = {"jsonrpc": "2.0", "id": 1, "result": ["1", "2", "3"]}

        diffs = computer.compute(resp1, resp2)
        assert len(diffs) == 3
        assert all(d.diff_type == "type_mismatch" for d in diffs)

    def test_nested_list_difference(self, computer: DiffComputer):
        """Test detection of differences in nested lists."""
        resp1 = {"jsonrpc": "2.0", "id": 1, "result": {"items": [[1, 2], [3, 4]]}}
        resp2 = {"jsonrpc": "2.0", "id": 1, "result": {"items": [[1, 2], [3, 5]]}}

        diffs = computer.compute(resp1, resp2)
        assert len(diffs) == 1
        assert diffs[0].path == "result.items[1][1]"


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


class TestDiffReporter:
    """Tests for DiffReporter class."""

    def test_save_diff_with_differences(self):
        """Test saving diff when differences exist."""
        with TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            reporter = DiffReporter(
                output_dir=output_dir,
                endpoint1_name="endpoint1",
                endpoint2_name="endpoint2",
            )

            request = {"method": "eth_blockNumber", "params": []}
            response1 = {"jsonrpc": "2.0", "id": 1, "result": "0x100"}
            response2 = {"jsonrpc": "2.0", "id": 1, "result": "0x200"}

            diffs = reporter.save_diff("eth_blockNumber", "block_1", request, response1, response2)

            assert len(diffs) == 1
            assert diffs[0].diff_type == "value_changed"

            # Check files were created
            diff_dir = output_dir / "eth_blockNumber" / "block_1"
            assert (diff_dir / "request.json").exists()
            assert (diff_dir / "endpoint1_response.json").exists()
            assert (diff_dir / "endpoint2_response.json").exists()
            assert (diff_dir / "diff.json").exists()
            assert (diff_dir / "diff.txt").exists()

            # Check request.json content
            request_data = json.loads((diff_dir / "request.json").read_text())
            assert request_data == request

            # Check diff.json content
            diff_data = json.loads((diff_dir / "diff.json").read_text())
            assert diff_data["method"] == "eth_blockNumber"
            assert diff_data["identifier"] == "block_1"
            assert diff_data["difference_count"] == 1

    def test_save_diff_no_differences(self):
        """Test saving diff when no differences exist."""
        with TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            reporter = DiffReporter(
                output_dir=output_dir,
                endpoint1_name="endpoint1",
                endpoint2_name="endpoint2",
            )

            request = {"method": "eth_blockNumber", "params": []}
            response = {"jsonrpc": "2.0", "id": 1, "result": "0x100"}

            diffs = reporter.save_diff("eth_blockNumber", "block_1", request, response, response)

            assert len(diffs) == 0

            # Check no files were created
            diff_dir = output_dir / "eth_blockNumber" / "block_1"
            assert not diff_dir.exists()

    def test_format_text_value_changed(self):
        """Test text formatting for value_changed difference."""
        with TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            reporter = DiffReporter(
                output_dir=output_dir,
                endpoint1_name="ep1",
                endpoint2_name="ep2",
            )

            diff = Difference(
                path="result.value",
                diff_type="value_changed",
                value1="0x100",
                value2="0x200",
            )

            text = reporter._format_text([diff])
            assert "result.value" in text
            assert "value_changed" in text
            assert "0x100" in text
            assert "0x200" in text

    def test_format_text_type_mismatch(self):
        """Test text formatting for type_mismatch difference."""
        with TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            reporter = DiffReporter(
                output_dir=output_dir,
                endpoint1_name="ep1",
                endpoint2_name="ep2",
            )

            diff = Difference(
                path="result.value",
                diff_type="type_mismatch",
                value1="string",
                value2=123,
                extra={"type1": "str", "type2": "int"},
            )

            text = reporter._format_text([diff])
            assert "type_mismatch" in text
            assert "str" in text
            assert "int" in text

    def test_format_text_missing_field(self):
        """Test text formatting for missing_in_endpoint2 difference."""
        with TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            reporter = DiffReporter(
                output_dir=output_dir,
                endpoint1_name="ep1",
                endpoint2_name="ep2",
            )

            diff = Difference(
                path="result.field",
                diff_type="missing_in_endpoint2",
                value1="value",
                value2=None,
            )

            text = reporter._format_text([diff])
            assert "missing_in_endpoint2" in text
            assert "(not present)" in text

    def test_format_text_added_field(self):
        """Test text formatting for added_in_endpoint2 difference."""
        with TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            reporter = DiffReporter(
                output_dir=output_dir,
                endpoint1_name="ep1",
                endpoint2_name="ep2",
            )

            diff = Difference(
                path="result.field",
                diff_type="added_in_endpoint2",
                value1=None,
                value2="value",
            )

            text = reporter._format_text([diff])
            assert "added_in_endpoint2" in text
            assert "(not present)" in text

    def test_format_text_length_mismatch(self):
        """Test text formatting for length_mismatch difference."""
        with TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            reporter = DiffReporter(
                output_dir=output_dir,
                endpoint1_name="ep1",
                endpoint2_name="ep2",
            )

            diff = Difference(
                path="result.items",
                diff_type="length_mismatch",
                extra={"length1": 3, "length2": 2},
            )

            text = reporter._format_text([diff])
            assert "length_mismatch" in text
            assert "3 elements" in text
            assert "2 elements" in text

    def test_format_text_error_vs_success(self):
        """Test text formatting for error_vs_success difference."""
        with TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            reporter = DiffReporter(
                output_dir=output_dir,
                endpoint1_name="ep1",
                endpoint2_name="ep2",
            )

            diff = Difference(
                path="(response)",
                diff_type="error_vs_success",
                value1="Error message",
                value2="Success response",
            )

            text = reporter._format_text([diff])
            assert "error_vs_success" in text
            assert "Error message" in text
            assert "Success response" in text

    def test_format_text_success_vs_error(self):
        """Test text formatting for success_vs_error difference."""
        with TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            reporter = DiffReporter(
                output_dir=output_dir,
                endpoint1_name="ep1",
                endpoint2_name="ep2",
            )

            diff = Difference(
                path="(response)",
                diff_type="success_vs_error",
                value1="Success response",
                value2="Error message",
            )

            text = reporter._format_text([diff])
            assert "success_vs_error" in text
            assert "Success response" in text
            assert "Error message" in text

    def test_format_text_error_message_differs(self):
        """Test text formatting for error_message_differs difference."""
        with TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            reporter = DiffReporter(
                output_dir=output_dir,
                endpoint1_name="ep1",
                endpoint2_name="ep2",
            )

            diff = Difference(
                path="(error)",
                diff_type="error_message_differs",
                value1="Error 1",
                value2="Error 2",
            )

            text = reporter._format_text([diff])
            assert "error_message_differs" in text
            assert "Error 1" in text
            assert "Error 2" in text

    def test_format_text_empty_list(self):
        """Test text formatting when no differences."""
        with TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            reporter = DiffReporter(
                output_dir=output_dir,
                endpoint1_name="ep1",
                endpoint2_name="ep2",
            )

            text = reporter._format_text([])
            assert text == "No differences found."

    def test_diff_to_dict(self):
        """Test conversion of Difference to dictionary."""
        with TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            reporter = DiffReporter(
                output_dir=output_dir,
                endpoint1_name="ep1",
                endpoint2_name="ep2",
            )

            diff = Difference(
                path="result.value",
                diff_type="value_changed",
                value1="old",
                value2="new",
                extra={"extra_key": "extra_value"},
            )

            diff_dict = reporter._diff_to_dict(diff)
            assert diff_dict["path"] == "result.value"
            assert diff_dict["type"] == "value_changed"
            assert diff_dict["ep1_value"] == "old"
            assert diff_dict["ep2_value"] == "new"
            assert diff_dict["extra_key"] == "extra_value"

    def test_diff_to_dict_with_none_values(self):
        """Test conversion when values are None."""
        with TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            reporter = DiffReporter(
                output_dir=output_dir,
                endpoint1_name="ep1",
                endpoint2_name="ep2",
            )

            diff = Difference(
                path="result.field",
                diff_type="missing_in_endpoint2",
                value1="value",
                value2=None,
            )

            diff_dict = reporter._diff_to_dict(diff)
            assert "ep1_value" in diff_dict
            assert "ep2_value" not in diff_dict  # None values are excluded

    def test_diff_to_dict_value1_none_value2_present(self):
        """Test conversion when value1 is None but value2 is present."""
        with TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            reporter = DiffReporter(
                output_dir=output_dir,
                endpoint1_name="ep1",
                endpoint2_name="ep2",
            )

            diff = Difference(
                path="result.field",
                diff_type="added_in_endpoint2",
                value1=None,
                value2="new_value",
            )

            diff_dict = reporter._diff_to_dict(diff)
            # When value1 is None, the branch at line 275 should skip adding ep1_value
            # but value2 is not None, so ep2_value should be added
            assert "ep1_value" not in diff_dict
            assert "ep2_value" in diff_dict
            assert diff_dict["ep2_value"] == "new_value"
