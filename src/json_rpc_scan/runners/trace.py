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

from json_rpc_scan.runners.base import BaseRunner, RunnerResult


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

    # Which trace types to request
    trace_types: list[str] = field(default_factory=lambda: list(DEFAULT_TRACE_TYPES))

    def to_types_array(self) -> list[str]:
        """Return trace types as array for RPC params."""
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
        """Run trace_block tests across a block range."""
        tests_run = 0
        diff_count = 0
        total_blocks = end_block - start_block + 1

        with tqdm(total=total_blocks, desc=self.method_name, unit="blk") as pbar:
            for block_num in range(start_block, end_block + 1):
                tests_run += 1
                # trace_block takes block number as hex string
                params: list[Any] = [hex(block_num)]

                resp1, resp2 = await self.client.call_both(
                    self.endpoints, self.method_name, params
                )

                if resp1.response != resp2.response:
                    diff_count += 1
                    self.log(f"\n⚠ Diff at block {block_num}")
                    self.reporter.save_diff(
                        method=self.method_name,
                        identifier=f"block_{block_num}",
                        request=resp1.request,
                        response1=resp1.response,
                        response2=resp2.response,
                    )

                pbar.update(1)

        self.log(f"\n{self.method_name}: {tests_run} blocks, {diff_count} diffs")
        return RunnerResult(self.method_name, tests_run, diff_count)


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
        """Run trace_transaction for all transactions in a block range."""
        # Collect all transaction hashes first
        self.log(f"{self.method_name}: Scanning for transactions...")
        tx_list: list[tuple[int, str]] = []

        for block_num in range(start_block, end_block + 1):
            block = await self.client.get_block(
                self.endpoints[0], block_num, full_transactions=True
            )
            if block and block.get("transactions"):
                for tx in block["transactions"]:
                    if isinstance(tx, dict) and tx.get("hash"):
                        tx_list.append((block_num, tx["hash"]))

        if not tx_list:
            self.log(f"{self.method_name}: No transactions found")
            return RunnerResult(self.method_name, 0, 0)

        self.log(f"{self.method_name}: Found {len(tx_list)} transactions")

        tests_run = 0
        diff_count = 0

        with tqdm(total=len(tx_list), desc=self.method_name, unit="tx") as pbar:
            for block_num, tx_hash in tx_list:
                tests_run += 1
                params: list[Any] = [tx_hash]

                resp1, resp2 = await self.client.call_both(
                    self.endpoints, self.method_name, params
                )

                if resp1.response != resp2.response:
                    diff_count += 1
                    self.log(f"\n⚠ Diff for tx {tx_hash[:16]}... (block {block_num})")
                    self.reporter.save_diff(
                        method=self.method_name,
                        identifier=f"tx_{tx_hash}",
                        request=resp1.request,
                        response1=resp1.response,
                        response2=resp2.response,
                    )

                pbar.update(1)

        self.log(f"\n{self.method_name}: {tests_run} txs, {diff_count} diffs")
        return RunnerResult(self.method_name, tests_run, diff_count)


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
        """Run trace_call by replaying transactions from a block range."""
        trace_options = kwargs.get("trace_options", TraceOptions())
        trace_types = trace_options.to_types_array()

        # Collect transactions to replay
        self.log(f"{self.method_name}: Scanning for transactions...")
        tx_list: list[tuple[int, str, dict[str, Any]]] = []

        for block_num in range(start_block, end_block + 1):
            block = await self.client.get_block(
                self.endpoints[0], block_num, full_transactions=True
            )
            if block and block.get("transactions"):
                for tx in block["transactions"]:
                    if isinstance(tx, dict):
                        call_obj = self._tx_to_call(tx)
                        tx_hash = tx.get("hash", f"unknown_{block_num}")
                        tx_list.append((block_num, tx_hash, call_obj))

        if not tx_list:
            self.log(f"{self.method_name}: No transactions found")
            return RunnerResult(self.method_name, 0, 0)

        self.log(f"{self.method_name}: Found {len(tx_list)} transactions")

        tests_run = 0
        diff_count = 0

        with tqdm(total=len(tx_list), desc=self.method_name, unit="call") as pbar:
            for block_num, tx_hash, call_obj in tx_list:
                tests_run += 1
                # Trace against the parent block's state
                state_block = hex(max(0, block_num - 1))
                # trace_call params: [callObject, traceTypes[], blockParameter]
                params: list[Any] = [call_obj, trace_types, state_block]

                resp1, resp2 = await self.client.call_both(
                    self.endpoints, self.method_name, params
                )

                if resp1.response != resp2.response:
                    diff_count += 1
                    self.log(f"\n⚠ Diff for {tx_hash[:16]}... @ block {block_num}")
                    self.reporter.save_diff(
                        method=self.method_name,
                        identifier=f"call_{tx_hash}",
                        request=resp1.request,
                        response1=resp1.response,
                        response2=resp2.response,
                    )

                pbar.update(1)

        self.log(f"\n{self.method_name}: {tests_run} calls, {diff_count} diffs")
        return RunnerResult(self.method_name, tests_run, diff_count)

    def _tx_to_call(self, tx: dict[str, Any]) -> dict[str, Any]:
        """Convert a transaction object to a call object."""
        call: dict[str, Any] = {}

        # Basic fields
        for key in ("from", "to", "gas", "value"):
            if tx.get(key):
                call[key] = tx[key]

        # Data field (called 'input' in tx, 'data' in call)
        if tx.get("input"):
            call["data"] = tx["input"]

        # Gas price - EIP-1559 vs legacy
        if tx.get("maxFeePerGas"):
            call["maxFeePerGas"] = tx["maxFeePerGas"]
            if tx.get("maxPriorityFeePerGas"):
                call["maxPriorityFeePerGas"] = tx["maxPriorityFeePerGas"]
        elif tx.get("gasPrice"):
            call["gasPrice"] = tx["gasPrice"]

        # Access list (EIP-2930)
        if tx.get("accessList"):
            call["accessList"] = tx["accessList"]

        return call


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
        """Run trace_callMany by batching transactions from blocks."""
        trace_options = kwargs.get("trace_options", TraceOptions())
        trace_types = trace_options.to_types_array()
        batch_size = kwargs.get("batch_size", 5)  # Calls per batch

        # Collect transactions and group by block
        self.log(f"{self.method_name}: Scanning for transactions...")
        blocks_with_txs: list[tuple[int, list[dict[str, Any]]]] = []

        for block_num in range(start_block, end_block + 1):
            block = await self.client.get_block(
                self.endpoints[0], block_num, full_transactions=True
            )
            if block and block.get("transactions"):
                txs = []
                for tx in block["transactions"]:
                    if isinstance(tx, dict):
                        txs.append(self._tx_to_call(tx))
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

        tests_run = 0
        diff_count = 0

        with tqdm(
            total=len(blocks_with_txs), desc=self.method_name, unit="blk"
        ) as pbar:
            for block_num, txs in blocks_with_txs:
                # Process in batches
                for i in range(0, len(txs), batch_size):
                    batch = txs[i : i + batch_size]
                    tests_run += 1

                    # Build callMany params: [[call, traceTypes], ...]
                    calls: list[list[Any]] = [[call, trace_types] for call in batch]

                    # Trace against the parent block's state
                    state_block = hex(max(0, block_num - 1))
                    params: list[Any] = [calls, state_block]

                    resp1, resp2 = await self.client.call_both(
                        self.endpoints, self.method_name, params
                    )

                    if resp1.response != resp2.response:
                        diff_count += 1
                        batch_id = f"block_{block_num}_batch_{i // batch_size}"
                        self.log(f"\n⚠ Diff for {batch_id}")
                        self.reporter.save_diff(
                            method=self.method_name,
                            identifier=batch_id,
                            request=resp1.request,
                            response1=resp1.response,
                            response2=resp2.response,
                        )

                pbar.update(1)

        self.log(f"\n{self.method_name}: {tests_run} batches, {diff_count} diffs")
        return RunnerResult(self.method_name, tests_run, diff_count)

    def _tx_to_call(self, tx: dict[str, Any]) -> dict[str, Any]:
        """Convert a transaction object to a call object."""
        call: dict[str, Any] = {}

        for key in ("from", "to", "gas", "value"):
            if tx.get(key):
                call[key] = tx[key]

        if tx.get("input"):
            call["data"] = tx["input"]

        if tx.get("maxFeePerGas"):
            call["maxFeePerGas"] = tx["maxFeePerGas"]
            if tx.get("maxPriorityFeePerGas"):
                call["maxPriorityFeePerGas"] = tx["maxPriorityFeePerGas"]
        elif tx.get("gasPrice"):
            call["gasPrice"] = tx["gasPrice"]

        if tx.get("accessList"):
            call["accessList"] = tx["accessList"]

        return call


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

    # Determine which trace type combinations to test
    if test_all_trace_types:
        # Test each trace type individually
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

            # Create output subdir for this trace type combination
            method_output = output_dir / type_display
            runner = TRACE_RUNNERS[method](client, endpoints, method_output)
            result = await runner.run(
                start_block, end_block, trace_options=current_options
            )

            # Include trace types in result method name for clarity
            if len(trace_type_sets) > 1:
                result = RunnerResult(
                    method=f"{result.method} ({type_display})",
                    tests_run=result.tests_run,
                    differences_found=result.differences_found,
                )

            results.append(result)

    return results
