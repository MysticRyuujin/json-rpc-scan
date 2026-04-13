"""Trace namespace JSON-RPC method runners.

Implements runners for Parity/OpenEthereum-style trace_* methods.
These are supported by Nethermind, Erigon, and Reth (but NOT Geth).

Supported methods:
- trace_block: Get traces for all transactions in a block
- trace_transaction: Get trace for a specific transaction
- trace_call: Execute and trace a call
- trace_callMany: Execute and trace multiple dependent calls

Trace types (can be combined):
- "trace": Basic execution trace with call hierarchy
- "vmTrace": Full VM execution trace with opcodes
- "stateDiff": State changes caused by the transaction

See:
- Erigon: https://erigon.gitbook.io/erigon/interacting-with-erigon/trace
- Reth: https://reth.rs/jsonrpc/trace.html
- Nethermind: https://docs.nethermind.io/interacting/json-rpc-ns/trace
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from tqdm import tqdm

from json_rpc_scan.runners.base import BaseRunner, RunnerResult, tx_to_call_obj


if TYPE_CHECKING:
    from pathlib import Path

    from json_rpc_scan.client import Endpoint, RPCClient


# Available trace types for trace_* methods
TRACE_TYPES: list[str] = ["trace", "vmTrace", "stateDiff"]

# Default trace types to use
DEFAULT_TRACE_TYPES: list[str] = ["trace"]


@dataclass
class TraceOptions:
    """Configuration for trace namespace methods.

    Unlike debug_* methods which use tracers, trace_* methods use
    trace types to specify what information to return.
    """

    trace_types: list[str] = field(default_factory=lambda: list(DEFAULT_TRACE_TYPES))

    def to_types_array(self) -> list[str]:
        return self.trace_types


class TraceBlockRunner(BaseRunner):
    """Runner for trace_block.

    Returns traces for all transactions in a block by number or tag.
    """

    method_name = "trace_block"
    description = "Get traces for all transactions in a block"

    async def run(
        self,
        start_block: int,
        end_block: int,
        **kwargs: Any,
    ) -> RunnerResult:
        inputs = [(f"block_{n}", [hex(n)]) for n in range(start_block, end_block + 1)]
        return await self.compare_over(inputs, total=len(inputs), unit="blk")


class TraceTransactionRunner(BaseRunner):
    """Runner for trace_transaction.

    Returns trace for a specific transaction by hash.
    """

    method_name = "trace_transaction"
    description = "Get trace for a specific transaction"

    async def run(
        self,
        start_block: int,
        end_block: int,
        **kwargs: Any,
    ) -> RunnerResult:
        self.log(f"{self.method_name}: Scanning for transactions...")
        inputs: list[tuple[str, list[Any]]] = []
        for block_num in range(start_block, end_block + 1):
            block = await self.client.get_block(
                self.endpoints[0], block_num, full_transactions=True
            )
            if not block or not block.get("transactions"):
                continue
            for tx in block["transactions"]:
                if isinstance(tx, dict) and tx.get("hash"):
                    inputs.append((f"tx_{tx['hash']}", [tx["hash"]]))

        if not inputs:
            self.log(f"{self.method_name}: No transactions found")
            return RunnerResult(self.method_name, 0, 0)

        self.log(f"{self.method_name}: Found {len(inputs)} transactions")
        return await self.compare_over(inputs, total=len(inputs), unit="tx")


class TraceCallRunner(BaseRunner):
    """Runner for trace_call.

    Executes and traces a call against historical state.
    Replays transactions from blocks to test trace consistency.
    """

    method_name = "trace_call"
    description = "Execute and trace a call against historical state"

    async def run(
        self,
        start_block: int,
        end_block: int,
        **kwargs: Any,
    ) -> RunnerResult:
        trace_types = kwargs.get("trace_options", TraceOptions()).to_types_array()

        self.log(f"{self.method_name}: Scanning for transactions...")
        inputs: list[tuple[str, list[Any]]] = []
        for block_num in range(start_block, end_block + 1):
            block = await self.client.get_block(
                self.endpoints[0], block_num, full_transactions=True
            )
            if not block or not block.get("transactions"):
                continue
            state_block = hex(max(0, block_num - 1))
            for tx in block["transactions"]:
                if not isinstance(tx, dict):
                    continue
                call_obj = tx_to_call_obj(tx)
                tx_hash = tx.get("hash", f"unknown_{block_num}")
                # trace_call params: [callObject, traceTypes[], blockParameter]
                inputs.append((f"call_{tx_hash}", [call_obj, trace_types, state_block]))

        if not inputs:
            self.log(f"{self.method_name}: No transactions found")
            return RunnerResult(self.method_name, 0, 0)

        self.log(f"{self.method_name}: Found {len(inputs)} transactions")
        return await self.compare_over(inputs, total=len(inputs), unit="call")


class TraceCallManyRunner(BaseRunner):
    """Runner for trace_callMany.

    Executes multiple dependent calls and traces them.
    Each call is executed on top of the previous calls' state changes.
    """

    method_name = "trace_callMany"
    description = "Execute and trace multiple dependent calls"

    async def run(
        self,
        start_block: int,
        end_block: int,
        **kwargs: Any,
    ) -> RunnerResult:
        trace_types = kwargs.get("trace_options", TraceOptions()).to_types_array()
        batch_size = kwargs.get("batch_size", 5)

        self.log(f"{self.method_name}: Scanning for transactions...")
        # Each entry: (block_num, tx_calls_for_that_block).
        blocks_with_txs: list[tuple[int, list[dict[str, Any]]]] = []
        for block_num in range(start_block, end_block + 1):
            block = await self.client.get_block(
                self.endpoints[0], block_num, full_transactions=True
            )
            if not block or not block.get("transactions"):
                continue
            txs: list[dict[str, Any]] = [
                tx_to_call_obj(tx)
                for tx in block["transactions"]
                if isinstance(tx, dict)
            ]
            if txs:
                blocks_with_txs.append((block_num, txs))

        if not blocks_with_txs:
            self.log(f"{self.method_name}: No transactions found")
            return RunnerResult(self.method_name, 0, 0)

        total_txs = sum(len(txs) for _, txs in blocks_with_txs)
        self.log(
            f"{self.method_name}: Found {total_txs} transactions "
            f"across {len(blocks_with_txs)} blocks"
        )

        # Build one (identifier, params) per batch.
        inputs: list[tuple[str, list[Any]]] = []
        for block_num, txs in blocks_with_txs:
            state_block = hex(max(0, block_num - 1))
            for i in range(0, len(txs), batch_size):
                batch = txs[i : i + batch_size]
                calls: list[list[Any]] = [[call, trace_types] for call in batch]
                identifier = f"block_{block_num}_batch_{i // batch_size}"
                inputs.append((identifier, [calls, state_block]))

        return await self.compare_over(inputs, total=len(inputs), unit="batch")


# Registry of trace runners
TRACE_RUNNERS: dict[str, type[BaseRunner]] = {
    "trace_block": TraceBlockRunner,
    "trace_transaction": TraceTransactionRunner,
    "trace_call": TraceCallRunner,
    "trace_callMany": TraceCallManyRunner,
}


async def run_trace_methods(
    client: RPCClient,
    endpoints: tuple[Endpoint, Endpoint],
    output_dir: Path,
    start_block: int,
    end_block: int,
    trace_options: TraceOptions | None = None,
    methods: list[str] | None = None,
    test_all_trace_types: bool = False,
) -> list[RunnerResult]:
    """Run trace method tests.

    Args:
        client: RPC client instance.
        endpoints: Two endpoints to compare.
        output_dir: Directory for diff output.
        start_block: First block to test.
        end_block: Last block to test.
        trace_options: Optional trace type configuration.
        methods: Specific methods to run (default: all).
        test_all_trace_types: If True, test each trace type separately.

    Returns:
        List of RunnerResult for each method tested.
    """
    if trace_options is None:
        trace_options = TraceOptions()

    methods_to_run = methods or list(TRACE_RUNNERS.keys())
    results: list[RunnerResult] = []

    if test_all_trace_types:
        trace_type_sets: list[list[str]] = [[t] for t in TRACE_TYPES]
    else:
        trace_type_sets = [trace_options.trace_types]

    for trace_type_set in trace_type_sets:
        current_options = TraceOptions(trace_types=trace_type_set)
        type_display = "+".join(trace_type_set)

        if len(trace_type_sets) > 1:
            tqdm.write(f"\n{'=' * 50}")
            tqdm.write(f"Testing with trace types: {type_display}")
            tqdm.write(f"{'=' * 50}")

        for method in methods_to_run:
            if method not in TRACE_RUNNERS:
                tqdm.write(f"⚠ Unknown method '{method}', skipping")
                continue

            method_output = output_dir / type_display
            runner = TRACE_RUNNERS[method](client, endpoints, method_output)
            result = await runner.run(
                start_block, end_block, trace_options=current_options
            )

            if len(trace_type_sets) > 1:
                result = RunnerResult(
                    method=f"{result.method} ({type_display})",
                    tests_run=result.tests_run,
                    differences_found=result.differences_found,
                )

            results.append(result)

    return results
