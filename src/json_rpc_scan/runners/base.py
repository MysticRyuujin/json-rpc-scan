"""Base class and shared helpers for JSON-RPC test runners.

The `BaseRunner.compare_one` / `compare_over` helpers centralize the
"call both endpoints, compare, save diff if they differ, log, advance
progress bar" loop that is otherwise duplicated in every runner. Runners
whose logic is a simple iteration over (identifier, params) pairs call
`compare_over` directly. Runners with multiple variants per logical item
(e.g. `eth_call` basic + state-override) call `compare_one` themselves
inside a custom `run()` body.

Comparison goes through `ResponseComparator`, which strips spec-irrelevant
differences (envelope fields, hex casing) and surfaces one-side-errored
as a distinct outcome so two different 500s don't compare equal via
empty-dict equality.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, ClassVar

from tqdm import tqdm

from json_rpc_scan.comparator import ResponseComparator
from json_rpc_scan.diff import DiffReporter


if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path

    from json_rpc_scan.client import Endpoint, RPCClient
    from json_rpc_scan.normalize import Normalizer


@dataclass
class RunnerResult:
    """Result from running a test runner."""

    method: str
    tests_run: int
    differences_found: int


class BaseRunner(ABC):
    """Abstract base class for test runners."""

    # Override in subclasses.
    method_name: str = ""
    description: str = ""
    # Opt-in normalizers for this method. Always-on normalizers
    # (strip_envelope, lowercase_hex) are added automatically by
    # ResponseComparator; declare anything method-specific here.
    extra_normalizers: ClassVar[list[Normalizer]] = []

    def __init__(
        self,
        client: RPCClient,
        endpoints: tuple[Endpoint, Endpoint],
        output_dir: Path,
    ) -> None:
        self.client = client
        self.endpoints = endpoints
        self.output_dir = output_dir
        self.reporter = DiffReporter(
            output_dir=output_dir,
            endpoint1_name=endpoints[0].name,
            endpoint2_name=endpoints[1].name,
            extra_normalizers=self.extra_normalizers,
        )
        self.comparator = ResponseComparator(extra_normalizers=self.extra_normalizers)

    @abstractmethod
    async def run(
        self,
        start_block: int,
        end_block: int,
        **kwargs: Any,
    ) -> RunnerResult:
        """Run the tests.

        Args:
            start_block: Starting block number.
            end_block: Ending block number.
            **kwargs: Additional runner-specific options.

        Returns:
            RunnerResult with statistics.
        """
        ...

    def log(self, message: str) -> None:
        """Log a message (compatible with tqdm progress bars)."""
        tqdm.write(message)

    async def compare_one(
        self,
        identifier: str,
        params: list[Any],
    ) -> bool:
        """Call both endpoints with the given params, compare, save diff if needed.

        The saved diff contains the post-normalization responses, so diff files
        match exactly what the gate compared.

        Returns:
            True if the comparison produced a diff (saved), False if equal.
        """
        resp1, resp2 = await self.client.call_both(
            self.endpoints, self.method_name, params
        )
        result = self.comparator.equal(resp1.response, resp2.response)
        if result.equal:
            return False

        self.log(f"\n⚠ {self.method_name} diff: {identifier}")
        self.reporter.save_diff(
            method=self.method_name,
            identifier=identifier,
            request=resp1.request,
            response1=result.normalized1,
            response2=result.normalized2,
        )
        return True

    async def compare_over(
        self,
        identifiers: Iterable[tuple[str, list[Any]]],
        *,
        total: int | None = None,
        unit: str = "req",
    ) -> RunnerResult:
        """Iterate (identifier, params) pairs and compare each via compare_one.

        Wraps the loop in a tqdm progress bar and returns a RunnerResult with
        totals. Collapses the ~70-line per-runner boilerplate to a one-liner.

        Args:
            identifiers: Iterable yielding `(identifier, params)` tuples.
            total: Optional total for the progress bar (for iterables with
                known length).
            unit: Progress bar unit label.
        """
        tests_run = 0
        diff_count = 0
        with tqdm(total=total, desc=self.method_name, unit=unit) as pbar:
            for identifier, params in identifiers:
                tests_run += 1
                if await self.compare_one(identifier, params):
                    diff_count += 1
                pbar.update(1)

        self.log(f"\n{self.method_name}: {tests_run} tests, {diff_count} diffs")
        return RunnerResult(self.method_name, tests_run, diff_count)


def tx_to_call_obj(
    tx: dict[str, Any],
    *,
    include_gas: bool = True,
    include_gas_pricing: bool = True,
    include_access_list: bool = True,
) -> dict[str, Any]:
    """Convert a transaction object into an eth_call-style call object.

    Replaces 6 copies of `_tx_to_call` across the runner modules. The three
    flags cover the distinct shapes:

    - Full (default): used by eth_call, debug_traceCall, trace_call, trace_callMany.
    - ``include_gas=False``: eth_estimateGas (the gas field is what's being
      estimated; passing it would short-circuit the result on some clients).
    - ``include_gas_pricing=False, include_access_list=False``:
      eth_createAccessList (the returned access list would include the passed
      one, distorting the result).
    """
    call: dict[str, Any] = {}

    base_fields = ("from", "to", "value")
    for key in base_fields:
        if tx.get(key):
            call[key] = tx[key]

    if include_gas and tx.get("gas"):
        call["gas"] = tx["gas"]

    if tx.get("input"):
        call["data"] = tx["input"]

    if include_gas_pricing:
        if tx.get("maxFeePerGas"):
            call["maxFeePerGas"] = tx["maxFeePerGas"]
            if tx.get("maxPriorityFeePerGas"):
                call["maxPriorityFeePerGas"] = tx["maxPriorityFeePerGas"]
        elif tx.get("gasPrice"):
            call["gasPrice"] = tx["gasPrice"]

    if include_access_list and tx.get("accessList"):
        call["accessList"] = tx["accessList"]

    return call
