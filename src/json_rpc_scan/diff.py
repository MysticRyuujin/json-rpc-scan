"""Diff computation and reporting for JSON-RPC responses."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any


if TYPE_CHECKING:
    from pathlib import Path


@dataclass
class Difference:
    """Represents a single difference between two responses."""

    path: str
    diff_type: str
    value1: Any = None
    value2: Any = None
    extra: dict[str, Any] = field(default_factory=dict)


class DiffComputer:
    """Computes differences between two JSON responses."""

    def compute(
        self, response1: dict[str, Any], response2: dict[str, Any]
    ) -> list[Difference]:
        """Compute differences between two JSON-RPC responses.

        Args:
            response1: First response dict.
            response2: Second response dict.

        Returns:
            List of Difference objects describing the changes.
        """
        differences: list[Difference] = []

        # Check for error vs success mismatch
        is_err1 = self._is_error(response1)
        is_err2 = self._is_error(response2)

        if is_err1 and not is_err2:
            differences.append(
                Difference(
                    path="(response)",
                    diff_type="error_vs_success",
                    value1=self._get_error_message(response1),
                    value2="Success response",
                )
            )
            return differences

        if not is_err1 and is_err2:
            differences.append(
                Difference(
                    path="(response)",
                    diff_type="success_vs_error",
                    value1="Success response",
                    value2=self._get_error_message(response2),
                )
            )
            return differences

        if is_err1 and is_err2:
            msg1 = self._get_error_message(response1)
            msg2 = self._get_error_message(response2)
            if msg1 != msg2:
                differences.append(
                    Difference(
                        path="(error)",
                        diff_type="error_message_differs",
                        value1=msg1,
                        value2=msg2,
                    )
                )
            return differences

        # Both are success - do detailed comparison
        self._compare_values(response1, response2, "", differences)
        return differences

    def _is_error(self, response: dict[str, Any]) -> bool:
        """Check if response indicates an error."""
        if "error" in response:
            return True
        result = response.get("result")
        return isinstance(result, dict) and "error" in result

    def _get_error_message(self, response: dict[str, Any]) -> str:
        """Extract error message from response."""
        if "error" in response:
            err = response["error"]
            if isinstance(err, dict):
                return str(err.get("message", err))
            return str(err)
        result = response.get("result")
        if isinstance(result, dict) and "error" in result:
            return str(result["error"])
        return "Unknown error"

    def _compare_values(
        self,
        val1: Any,
        val2: Any,
        path: str,
        differences: list[Difference],
    ) -> None:
        """Recursively compare two values."""
        if type(val1) is not type(val2):
            differences.append(
                Difference(
                    path=path,
                    diff_type="type_mismatch",
                    value1=val1,
                    value2=val2,
                    extra={
                        "type1": type(val1).__name__,
                        "type2": type(val2).__name__,
                    },
                )
            )
        elif isinstance(val1, dict):
            self._compare_dicts(val1, val2, path, differences)
        elif isinstance(val1, list):
            self._compare_lists(val1, val2, path, differences)
        elif val1 != val2:
            differences.append(
                Difference(
                    path=path,
                    diff_type="value_changed",
                    value1=val1,
                    value2=val2,
                )
            )

    def _compare_dicts(
        self,
        dict1: dict[str, Any],
        dict2: dict[str, Any],
        path: str,
        differences: list[Difference],
    ) -> None:
        """Compare two dictionaries."""
        all_keys = set(dict1.keys()) | set(dict2.keys())

        for key in sorted(all_keys):
            new_path = f"{path}.{key}" if path else key

            if key not in dict1:
                differences.append(
                    Difference(
                        path=new_path,
                        diff_type="added_in_endpoint2",
                        value1=None,
                        value2=dict2[key],
                    )
                )
            elif key not in dict2:
                differences.append(
                    Difference(
                        path=new_path,
                        diff_type="missing_in_endpoint2",
                        value1=dict1[key],
                        value2=None,
                    )
                )
            else:
                self._compare_values(dict1[key], dict2[key], new_path, differences)

    def _compare_lists(
        self,
        list1: list[Any],
        list2: list[Any],
        path: str,
        differences: list[Difference],
    ) -> None:
        """Compare two lists."""
        if len(list1) != len(list2):
            differences.append(
                Difference(
                    path=path,
                    diff_type="length_mismatch",
                    extra={"length1": len(list1), "length2": len(list2)},
                )
            )

        for i in range(min(len(list1), len(list2))):
            self._compare_values(list1[i], list2[i], f"{path}[{i}]", differences)


class DiffReporter:
    """Reports and saves diff results."""

    def __init__(
        self,
        output_dir: Path,
        endpoint1_name: str,
        endpoint2_name: str,
    ) -> None:
        """Initialize the reporter.

        Args:
            output_dir: Directory to save reports.
            endpoint1_name: Name of the first endpoint.
            endpoint2_name: Name of the second endpoint.
        """
        self.output_dir = output_dir
        self.endpoint1_name = endpoint1_name
        self.endpoint2_name = endpoint2_name
        self._computer = DiffComputer()

    def save_diff(
        self,
        method: str,
        identifier: str,
        request: dict[str, Any],
        response1: dict[str, Any],
        response2: dict[str, Any],
    ) -> list[Difference]:
        """Compute and save a diff between two responses.

        Args:
            method: The RPC method name.
            identifier: Unique identifier (e.g., block number, tx hash).
            request: The request payload.
            response1: Response from endpoint 1.
            response2: Response from endpoint 2.

        Returns:
            List of differences found.
        """
        differences = self._computer.compute(response1, response2)

        if differences:
            diff_dir = self.output_dir / method / identifier
            diff_dir.mkdir(parents=True, exist_ok=True)

            # Save request
            (diff_dir / "request.json").write_text(json.dumps(request, indent=2))

            # Save responses
            (diff_dir / f"{self.endpoint1_name}_response.json").write_text(
                json.dumps(response1, indent=2)
            )
            (diff_dir / f"{self.endpoint2_name}_response.json").write_text(
                json.dumps(response2, indent=2)
            )

            # Save diff JSON
            diff_data = {
                "method": method,
                "identifier": identifier,
                "endpoint1": self.endpoint1_name,
                "endpoint2": self.endpoint2_name,
                "difference_count": len(differences),
                "differences": [self._diff_to_dict(d) for d in differences],
            }
            (diff_dir / "diff.json").write_text(json.dumps(diff_data, indent=2))

            # Save diff text
            (diff_dir / "diff.txt").write_text(self._format_text(differences))

        return differences

    def _diff_to_dict(self, diff: Difference) -> dict[str, Any]:
        """Convert a Difference to a dictionary."""
        d: dict[str, Any] = {
            "path": diff.path,
            "type": diff.diff_type,
        }
        if diff.value1 is not None:
            d[f"{self.endpoint1_name}_value"] = diff.value1
        if diff.value2 is not None:
            d[f"{self.endpoint2_name}_value"] = diff.value2
        if diff.extra:
            d.update(diff.extra)
        return d

    def _format_text(self, differences: list[Difference]) -> str:
        """Format differences as human-readable text."""
        if not differences:
            return "No differences found."

        lines = [
            f"Found {len(differences)} difference(s):",
            "=" * 60,
            "",
        ]

        for i, diff in enumerate(differences, 1):
            path = diff.path or "(root)"
            lines.append(f"[{i}] Path: {path}")
            lines.append(f"    Type: {diff.diff_type}")

            if diff.diff_type == "value_changed":
                lines.append(f"    {self.endpoint1_name}: {json.dumps(diff.value1)}")
                lines.append(f"    {self.endpoint2_name}: {json.dumps(diff.value2)}")
            elif diff.diff_type == "type_mismatch":
                t1 = diff.extra.get("type1", "unknown")
                t2 = diff.extra.get("type2", "unknown")
                v1 = json.dumps(diff.value1)
                v2 = json.dumps(diff.value2)
                lines.append(f"    {self.endpoint1_name}: {t1} = {v1}")
                lines.append(f"    {self.endpoint2_name}: {t2} = {v2}")
            elif diff.diff_type == "missing_in_endpoint2":
                lines.append(f"    {self.endpoint1_name}: {json.dumps(diff.value1)}")
                lines.append(f"    {self.endpoint2_name}: (not present)")
            elif diff.diff_type == "added_in_endpoint2":
                lines.append(f"    {self.endpoint1_name}: (not present)")
                lines.append(f"    {self.endpoint2_name}: {json.dumps(diff.value2)}")
            elif diff.diff_type == "length_mismatch":
                len1 = diff.extra.get("length1", "?")
                len2 = diff.extra.get("length2", "?")
                lines.append(f"    {self.endpoint1_name}: {len1} elements")
                lines.append(f"    {self.endpoint2_name}: {len2} elements")
            elif diff.diff_type in (
                "error_vs_success",
                "success_vs_error",
                "error_message_differs",
            ):
                lines.append(f"    {self.endpoint1_name}: {diff.value1}")
                lines.append(f"    {self.endpoint2_name}: {diff.value2}")

            lines.append("")

        return "\n".join(lines)
