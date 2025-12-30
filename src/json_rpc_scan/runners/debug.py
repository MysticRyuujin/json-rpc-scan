"""Debug namespace JSON-RPC method runners.

Implements runners for Geth debug_* methods as documented at:
https://geth.ethereum.org/docs/interacting-with-geth/rpc/ns-debug

Supported methods:
- debug_traceBlockByNumber: Trace all txs in a block by number
- debug_traceBlockByHash: Trace all txs in a block by hash
- debug_traceTransaction: Trace a specific transaction
- debug_traceCall: Execute and trace an eth_call
- debug_getBadBlocks: Get list of bad blocks seen by the client
- debug_getRawBlock: Get RLP-encoded block by number
- debug_getRawHeader: Get RLP-encoded header by block number
- debug_getRawReceipts: Get RLP-encoded receipts for a block

TraceConfig options (per Geth docs):
- tracer: string - Built-in tracer name (callTracer, prestateTracer, 4byteTracer)
                   or custom JS expression. If omitted, uses struct/opcode logger.
- tracerConfig: object - Tracer-specific config (e.g., {onlyTopCall: true})
- timeout: string - Override default 5s timeout (e.g., "10s")
- reexec: uint64 - Blocks to re-execute for missing state (default 128)

Opcode logger options (when tracer not specified):
- enableMemory: bool - Capture EVM memory (default: false)
- disableStack: bool - Disable stack capture (default: false)
- disableStorage: bool - Disable storage capture (default: false)
- enableReturnData: bool - Capture return data (default: false)

Built-in tracers:
- (none) - struct/opcode logger: raw EVM execution trace
- callTracer - tracks all call frames with gas, value, input/output
- prestateTracer - returns pre-execution state of touched accounts
- 4byteTracer - collects function selector statistics
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from tqdm import tqdm

from json_rpc_scan.runners.base import BaseRunner, RunnerResult


if TYPE_CHECKING:
    from pathlib import Path

    from json_rpc_scan.client import Endpoint, RPCClient


# Built-in tracers to test when no specific tracer is requested
BUILTIN_TRACERS: list[str | None] = [
    None,  # struct/opcode logger
    "callTracer",
    "prestateTracer",
    "4byteTracer",
]


@dataclass
class TraceConfig:
    """Configuration for debug trace methods.

    By default (no options), Geth uses the struct/opcode logger which provides
    the most complete raw EVM trace. Built-in tracers like callTracer provide
    more structured but less detailed output.

    See: https://geth.ethereum.org/docs/developers/evm-tracing/built-in-tracers
    """

    # Tracer selection (None = struct/opcode logger)
    tracer: str | None = None
    tracer_config: dict[str, Any] | None = None

    # General trace options
    timeout: str | None = None  # e.g., "10s"
    reexec: int | None = None  # blocks to re-execute

    # Opcode logger options (only used when tracer is None)
    enable_memory: bool = False
    disable_stack: bool = False
    disable_storage: bool = False
    enable_return_data: bool = False

    def to_params(self) -> dict[str, Any]:
        """Convert to JSON-RPC trace config parameters."""
        params: dict[str, Any] = {}

        if self.tracer:
            params["tracer"] = self.tracer
            if self.tracer_config:
                params["tracerConfig"] = self.tracer_config
        else:
            # Opcode logger options
            if self.enable_memory:
                params["enableMemory"] = True
            if self.disable_stack:
                params["disableStack"] = True
            if self.disable_storage:
                params["disableStorage"] = True
            if self.enable_return_data:
                params["enableReturnData"] = True

        if self.timeout:
            params["timeout"] = self.timeout
        if self.reexec is not None:
            params["reexec"] = self.reexec

        return params

    def with_tracer(self, tracer: str | None) -> TraceConfig:
        """Create a copy with a different tracer."""
        return TraceConfig(
            tracer=tracer,
            tracer_config=self.tracer_config if tracer == self.tracer else None,
            timeout=self.timeout,
            reexec=self.reexec,
            enable_memory=self.enable_memory,
            disable_stack=self.disable_stack,
            disable_storage=self.disable_storage,
            enable_return_data=self.enable_return_data,
        )


def tracer_name(tracer: str | None) -> str:
    """Get display name for a tracer."""
    return tracer if tracer else "structLogger"


class DebugTraceBlockByNumberRunner(BaseRunner):
    """Runner for debug_traceBlockByNumber.

    Traces all transactions in a block, returning structured logs for each.
    """

    method_name = "debug_traceBlockByNumber"
    description = "Trace all transactions in a block by number"

    async def run(
        self,
        start_block: int,
        end_block: int,
        **kwargs: Any,
    ) -> RunnerResult:
        """Run debug_traceBlockByNumber tests across a block range."""
        trace_config = kwargs.get("trace_config", TraceConfig())
        trace_params = trace_config.to_params()

        tests_run = 0
        diff_count = 0
        total_blocks = end_block - start_block + 1

        with tqdm(total=total_blocks, desc=self.method_name, unit="blk") as pbar:
            for block_num in range(start_block, end_block + 1):
                tests_run += 1
                params: list[Any] = [hex(block_num)]
                if trace_params:
                    params.append(trace_params)

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


class DebugTraceBlockByHashRunner(BaseRunner):
    """Runner for debug_traceBlockByHash.

    Same as traceBlockByNumber but uses block hash instead.
    """

    method_name = "debug_traceBlockByHash"
    description = "Trace all transactions in a block by hash"

    async def run(
        self,
        start_block: int,
        end_block: int,
        **kwargs: Any,
    ) -> RunnerResult:
        """Run debug_traceBlockByHash tests across a block range."""
        trace_config = kwargs.get("trace_config", TraceConfig())
        trace_params = trace_config.to_params()

        tests_run = 0
        diff_count = 0
        total_blocks = end_block - start_block + 1

        with tqdm(total=total_blocks, desc=self.method_name, unit="blk") as pbar:
            for block_num in range(start_block, end_block + 1):
                block = await self.client.get_block(
                    self.endpoints[0], block_num, full_transactions=False
                )
                if not block or not block.get("hash"):
                    pbar.update(1)
                    continue

                block_hash = block["hash"]
                tests_run += 1
                params: list[Any] = [block_hash]
                if trace_params:
                    params.append(trace_params)

                resp1, resp2 = await self.client.call_both(
                    self.endpoints, self.method_name, params
                )

                if resp1.response != resp2.response:
                    diff_count += 1
                    self.log(f"\n⚠ Diff at block {block_num} ({block_hash[:16]}...)")
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


class DebugTraceTransactionRunner(BaseRunner):
    """Runner for debug_traceTransaction.

    Traces individual transactions by hash, replaying them exactly as executed.
    """

    method_name = "debug_traceTransaction"
    description = "Trace individual transactions by hash"

    async def run(
        self,
        start_block: int,
        end_block: int,
        **kwargs: Any,
    ) -> RunnerResult:
        """Run debug_traceTransaction for all transactions in a block range."""
        trace_config = kwargs.get("trace_config", TraceConfig())
        trace_params = trace_config.to_params()

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
                if trace_params:
                    params.append(trace_params)

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


class DebugTraceCallRunner(BaseRunner):
    """Runner for debug_traceCall.

    Executes eth_call-style transactions and traces them against historical state.
    Also validates that trace results are consistent with on-chain tx status:
    - If a tx succeeded on-chain but trace errors, that indicates a bug.
    - If a tx failed on-chain, we expect the trace to also show an error.
    """

    method_name = "debug_traceCall"
    description = "Trace eth_call execution against historical state"

    async def run(
        self,
        start_block: int,
        end_block: int,
        **kwargs: Any,
    ) -> RunnerResult:
        """Run debug_traceCall by replaying transactions from a block range."""
        trace_config = kwargs.get("trace_config", TraceConfig())
        trace_params = trace_config.to_params()

        # Collect transactions to replay with their on-chain status
        self.log(f"{self.method_name}: Scanning for transactions...")
        # tx_list entries: (block_num, tx_hash, call_obj, tx_succeeded)
        tx_list: list[tuple[int, str, dict[str, Any], bool]] = []

        for block_num in range(start_block, end_block + 1):
            block = await self.client.get_block(
                self.endpoints[0], block_num, full_transactions=True
            )
            if block and block.get("transactions"):
                for tx in block["transactions"]:
                    if isinstance(tx, dict):
                        call_obj = self._tx_to_call(tx)
                        tx_hash = tx.get("hash", f"unknown_{block_num}")

                        # Get receipt to determine on-chain success/failure
                        receipt = await self.client.get_transaction_receipt(
                            self.endpoints[0], tx_hash
                        )
                        # status: 0x1 = success, 0x0 = failure (post-Byzantium)
                        # Pre-Byzantium txs may not have status field
                        tx_succeeded = True
                        if receipt and receipt.get("status"):
                            tx_succeeded = receipt["status"] == "0x1"

                        tx_list.append((block_num, tx_hash, call_obj, tx_succeeded))

        if not tx_list:
            self.log(f"{self.method_name}: No transactions found")
            return RunnerResult(self.method_name, 0, 0)

        self.log(f"{self.method_name}: Found {len(tx_list)} transactions")

        tests_run = 0
        diff_count = 0
        status_mismatch_count = 0

        with tqdm(total=len(tx_list), desc=self.method_name, unit="call") as pbar:
            for block_num, tx_hash, call_obj, tx_succeeded in tx_list:
                tests_run += 1
                # Trace against the parent block's state
                state_block = hex(max(0, block_num - 1))
                params: list[Any] = [call_obj, state_block]
                if trace_params:
                    params.append(trace_params)

                resp1, resp2 = await self.client.call_both(
                    self.endpoints, self.method_name, params
                )

                # Check for endpoint differences
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

                # Check for status/trace mismatches on each endpoint
                for resp in [resp1, resp2]:
                    trace_errored = self._trace_has_error(resp.response)
                    if tx_succeeded and trace_errored:
                        status_mismatch_count += 1
                        self.log(
                            f"\n🚨 Status mismatch ({resp.endpoint.name}): "
                            f"tx {tx_hash[:16]}... succeeded on-chain but trace errored"
                        )
                        self.reporter.save_diff(
                            method=self.method_name,
                            identifier=f"status_mismatch_{resp.endpoint.name}_{tx_hash}",
                            request=resp.request,
                            response1={"tx_status": "success", "expected": "trace OK"},
                            response2={
                                "trace_error": self._get_trace_error(resp.response)
                            },
                        )

                pbar.update(1)

        self.log(
            f"\n{self.method_name}: {tests_run} calls, {diff_count} diffs, "
            f"{status_mismatch_count} status mismatches"
        )
        return RunnerResult(self.method_name, tests_run, diff_count)

    def _trace_has_error(self, response: dict[str, Any]) -> bool:
        """Check if a trace response indicates an error.

        Handles multiple trace formats:
        - RPC error: response["error"] is set
        - callTracer: result has "error" field
        - structLogger: result has "failed" = true
        """
        # RPC-level error
        if response.get("error"):
            return True

        result = response.get("result")
        if not result:
            return False

        # callTracer format: {"type": "CALL", "error": "execution reverted", ...}
        if isinstance(result, dict):
            if result.get("error"):
                return True
            # structLogger format: {"gas": ..., "failed": true, ...}
            if result.get("failed"):
                return True

        return False

    def _get_trace_error(self, response: dict[str, Any]) -> str:
        """Extract the error message from a trace response."""
        if response.get("error"):
            err = response["error"]
            if isinstance(err, dict):
                msg = err.get("message")
                return str(msg) if msg else str(err)
            return str(err)

        result = response.get("result")
        if isinstance(result, dict):
            if result.get("error"):
                return str(result["error"])
            if result.get("failed"):
                return "execution failed"

        return "unknown error"

    def _tx_to_call(self, tx: dict[str, Any]) -> dict[str, Any]:
        """Convert a transaction object to an eth_call-style object."""
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


class DebugGetBadBlocksRunner(BaseRunner):
    """Runner for debug_getBadBlocks.

    Returns a list of the last 'bad blocks' that the client has seen on the network.
    These are blocks that failed validation.
    """

    method_name = "debug_getBadBlocks"
    description = "Get list of bad blocks seen by the client"

    async def run(
        self,
        start_block: int,
        end_block: int,
        **kwargs: Any,
    ) -> RunnerResult:
        """Run debug_getBadBlocks comparison (single call, no parameters)."""
        tests_run = 1
        diff_count = 0

        resp1, resp2 = await self.client.call_both(self.endpoints, self.method_name, [])

        if resp1.response != resp2.response:
            diff_count += 1
            self.log(f"\n⚠ Diff in {self.method_name}")
            self.reporter.save_diff(
                method=self.method_name,
                identifier="bad_blocks",
                request=resp1.request,
                response1=resp1.response,
                response2=resp2.response,
            )

        self.log(f"\n{self.method_name}: {tests_run} test, {diff_count} diffs")
        return RunnerResult(self.method_name, tests_run, diff_count)


class DebugGetRawBlockRunner(BaseRunner):
    """Runner for debug_getRawBlock.

    Retrieves and returns the RLP-encoded block by number.
    """

    method_name = "debug_getRawBlock"
    description = "Get RLP-encoded block by number"

    async def run(
        self,
        start_block: int,
        end_block: int,
        **kwargs: Any,
    ) -> RunnerResult:
        """Run debug_getRawBlock tests across a block range."""
        tests_run = 0
        diff_count = 0
        total_blocks = end_block - start_block + 1

        with tqdm(total=total_blocks, desc=self.method_name, unit="blk") as pbar:
            for block_num in range(start_block, end_block + 1):
                tests_run += 1
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


class DebugGetRawHeaderRunner(BaseRunner):
    """Runner for debug_getRawHeader.

    Returns an RLP-encoded header for a given block number.
    """

    method_name = "debug_getRawHeader"
    description = "Get RLP-encoded header by block number"

    async def run(
        self,
        start_block: int,
        end_block: int,
        **kwargs: Any,
    ) -> RunnerResult:
        """Run debug_getRawHeader tests across a block range."""
        tests_run = 0
        diff_count = 0
        total_blocks = end_block - start_block + 1

        with tqdm(total=total_blocks, desc=self.method_name, unit="blk") as pbar:
            for block_num in range(start_block, end_block + 1):
                tests_run += 1
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


class DebugGetRawReceiptsRunner(BaseRunner):
    """Runner for debug_getRawReceipts.

    Returns the consensus-encoding of all transaction receipts within a single block.
    """

    method_name = "debug_getRawReceipts"
    description = "Get RLP-encoded receipts for a block"

    async def run(
        self,
        start_block: int,
        end_block: int,
        **kwargs: Any,
    ) -> RunnerResult:
        """Run debug_getRawReceipts tests across a block range."""
        tests_run = 0
        diff_count = 0
        total_blocks = end_block - start_block + 1

        with tqdm(total=total_blocks, desc=self.method_name, unit="blk") as pbar:
            for block_num in range(start_block, end_block + 1):
                tests_run += 1
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


# Registry of debug runners
DEBUG_RUNNERS: dict[str, type[BaseRunner]] = {
    "debug_traceBlockByNumber": DebugTraceBlockByNumberRunner,
    "debug_traceBlockByHash": DebugTraceBlockByHashRunner,
    "debug_traceTransaction": DebugTraceTransactionRunner,
    "debug_traceCall": DebugTraceCallRunner,
    "debug_getBadBlocks": DebugGetBadBlocksRunner,
    "debug_getRawBlock": DebugGetRawBlockRunner,
    "debug_getRawHeader": DebugGetRawHeaderRunner,
    "debug_getRawReceipts": DebugGetRawReceiptsRunner,
}


async def run_debug_methods(
    client: RPCClient,
    endpoints: tuple[Endpoint, Endpoint],
    output_dir: Path,
    start_block: int,
    end_block: int,
    trace_config: TraceConfig | None = None,
    methods: list[str] | None = None,
    test_all_tracers: bool = False,
    tracers: list[str | None] | None = None,
) -> list[RunnerResult]:
    """Run debug method tests.

    Args:
        client: RPC client instance.
        endpoints: Two endpoints to compare.
        output_dir: Directory for diff output.
        start_block: First block to test.
        end_block: Last block to test.
        trace_config: Optional trace configuration.
        methods: Specific methods to run (default: all).
        test_all_tracers: If True, run each method with multiple tracers.
        tracers: Specific tracers to test (used with test_all_tracers).

    Returns:
        List of RunnerResult for each method tested.
    """
    if trace_config is None:
        trace_config = TraceConfig()

    methods_to_run = methods or list(DEBUG_RUNNERS.keys())
    results: list[RunnerResult] = []

    # Determine which tracers to test
    if test_all_tracers:
        tracers_to_test = tracers if tracers is not None else list(BUILTIN_TRACERS)
    else:
        tracers_to_test = [trace_config.tracer]

    for tracer in tracers_to_test:
        current_config = trace_config.with_tracer(tracer)
        tracer_display = tracer_name(tracer)

        if len(tracers_to_test) > 1:
            tqdm.write(f"\n{'=' * 50}")
            tqdm.write(f"Testing with tracer: {tracer_display}")
            tqdm.write(f"{'=' * 50}")

        for method in methods_to_run:
            if method not in DEBUG_RUNNERS:
                tqdm.write(f"⚠ Unknown method '{method}', skipping")
                continue

            # Create output subdir for this tracer
            method_output = output_dir / tracer_display
            runner = DEBUG_RUNNERS[method](client, endpoints, method_output)
            result = await runner.run(
                start_block, end_block, trace_config=current_config
            )

            # Include tracer in result method name for clarity
            if len(tracers_to_test) > 1:
                result = RunnerResult(
                    method=f"{result.method} ({tracer_display})",
                    tests_run=result.tests_run,
                    differences_found=result.differences_found,
                )

            results.append(result)

    return results
