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

from json_rpc_scan.runners.base import BaseRunner, RunnerResult, tx_to_call_obj


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


def _with_trace_params(base: list[Any], trace_params: dict[str, Any]) -> list[Any]:
    """Append trace config to params list if non-empty."""
    if trace_params:
        return [*base, trace_params]
    return base


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
        trace_params = kwargs.get("trace_config", TraceConfig()).to_params()
        total = end_block - start_block + 1

        def inputs() -> list[tuple[str, list[Any]]]:
            return [
                (f"block_{n}", _with_trace_params([hex(n)], trace_params))
                for n in range(start_block, end_block + 1)
            ]

        return await self.compare_over(inputs(), total=total, unit="blk")


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
        trace_params = kwargs.get("trace_config", TraceConfig()).to_params()

        inputs: list[tuple[str, list[Any]]] = []
        for block_num in range(start_block, end_block + 1):
            block = await self.client.get_block(
                self.endpoints[0], block_num, full_transactions=False
            )
            if not block or not block.get("hash"):
                continue
            params = _with_trace_params([block["hash"]], trace_params)
            inputs.append((f"block_{block_num}", params))

        return await self.compare_over(inputs, total=len(inputs), unit="blk")


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
        trace_params = kwargs.get("trace_config", TraceConfig()).to_params()

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
                    params = _with_trace_params([tx["hash"]], trace_params)
                    inputs.append((f"tx_{tx['hash']}", params))

        if not inputs:
            self.log(f"{self.method_name}: No transactions found")
            return RunnerResult(self.method_name, 0, 0)

        self.log(f"{self.method_name}: Found {len(inputs)} transactions")
        return await self.compare_over(inputs, total=len(inputs), unit="tx")


class DebugTraceCallRunner(BaseRunner):
    """Runner for debug_traceCall.

    Executes eth_call-style transactions and traces them against historical state.
    Also validates that trace results are consistent with on-chain tx status:
    - If a tx succeeded on-chain but trace errors, that indicates a bug.
    - If a tx failed on-chain, we expect the trace to also show an error.

    Multi-variant runner: per tx, compares endpoints AND checks each endpoint's
    trace output against the on-chain receipt status independently.
    """

    method_name = "debug_traceCall"
    description = "Trace eth_call execution against historical state"

    async def run(
        self,
        start_block: int,
        end_block: int,
        **kwargs: Any,
    ) -> RunnerResult:
        trace_params = kwargs.get("trace_config", TraceConfig()).to_params()

        self.log(f"{self.method_name}: Scanning for transactions...")
        # Entries are (block_num, tx_hash, call_obj, tx_succeeded).
        tx_list: list[tuple[int, str, dict[str, Any], bool]] = []

        for block_num in range(start_block, end_block + 1):
            block = await self.client.get_block(
                self.endpoints[0], block_num, full_transactions=True
            )
            if not block or not block.get("transactions"):
                continue
            for tx in block["transactions"]:
                if not isinstance(tx, dict):
                    continue
                call_obj = tx_to_call_obj(tx)
                tx_hash = tx.get("hash", f"unknown_{block_num}")
                receipt = await self.client.get_transaction_receipt(
                    self.endpoints[0], tx_hash
                )
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
                state_block = hex(max(0, block_num - 1))
                params = _with_trace_params([call_obj, state_block], trace_params)

                resp1, resp2 = await self.client.call_both(
                    self.endpoints, self.method_name, params
                )
                result = self.comparator.equal(resp1.response, resp2.response)

                if not result.equal:
                    diff_count += 1
                    self.log(
                        f"\n⚠ {self.method_name} diff: "
                        f"{tx_hash[:16]}... @ block {block_num}"
                    )
                    self.reporter.save_diff(
                        method=self.method_name,
                        identifier=f"call_{tx_hash}",
                        request=resp1.request,
                        response1=result.normalized1,
                        response2=result.normalized2,
                    )

                # Check per-endpoint status/trace mismatch — a tx that succeeded
                # on-chain but whose trace reports an error is a client bug
                # regardless of whether the two endpoints agree.
                for resp in (resp1, resp2):
                    if tx_succeeded and self._trace_has_error(resp.response):
                        status_mismatch_count += 1
                        self.log(
                            f"\n🚨 Status mismatch ({resp.endpoint.name}): "
                            f"tx {tx_hash[:16]}... succeeded on-chain "
                            f"but trace errored"
                        )
                        self.reporter.save_diff(
                            method=self.method_name,
                            identifier=(
                                f"status_mismatch_{resp.endpoint.name}_{tx_hash}"
                            ),
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
        if response.get("error"):
            return True

        result = response.get("result")
        if not result:
            return False

        if isinstance(result, dict):
            if result.get("error"):
                return True
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


class DebugGetBadBlocksRunner(BaseRunner):
    """Runner for debug_getBadBlocks.

    Returns a list of the last 'bad blocks' the client has seen.
    Single call, no parameters.
    """

    method_name = "debug_getBadBlocks"
    description = "Get list of bad blocks seen by the client"

    async def run(
        self,
        start_block: int,
        end_block: int,
        **kwargs: Any,
    ) -> RunnerResult:
        return await self.compare_over([("bad_blocks", [])], total=1, unit="req")


class DebugGetRawBlockRunner(BaseRunner):
    """Runner for debug_getRawBlock. Returns RLP-encoded block by number."""

    method_name = "debug_getRawBlock"
    description = "Get RLP-encoded block by number"

    async def run(
        self,
        start_block: int,
        end_block: int,
        **kwargs: Any,
    ) -> RunnerResult:
        inputs = [(f"block_{n}", [hex(n)]) for n in range(start_block, end_block + 1)]
        return await self.compare_over(inputs, total=len(inputs), unit="blk")


class DebugGetRawHeaderRunner(BaseRunner):
    """Runner for debug_getRawHeader. Returns RLP-encoded header."""

    method_name = "debug_getRawHeader"
    description = "Get RLP-encoded header by block number"

    async def run(
        self,
        start_block: int,
        end_block: int,
        **kwargs: Any,
    ) -> RunnerResult:
        inputs = [(f"block_{n}", [hex(n)]) for n in range(start_block, end_block + 1)]
        return await self.compare_over(inputs, total=len(inputs), unit="blk")


class DebugGetRawReceiptsRunner(BaseRunner):
    """Runner for debug_getRawReceipts. Returns RLP-encoded receipts."""

    method_name = "debug_getRawReceipts"
    description = "Get RLP-encoded receipts for a block"

    async def run(
        self,
        start_block: int,
        end_block: int,
        **kwargs: Any,
    ) -> RunnerResult:
        inputs = [(f"block_{n}", [hex(n)]) for n in range(start_block, end_block + 1)]
        return await self.compare_over(inputs, total=len(inputs), unit="blk")


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

            method_output = output_dir / tracer_display
            runner = DEBUG_RUNNERS[method](client, endpoints, method_output)
            result = await runner.run(
                start_block, end_block, trace_config=current_config
            )

            if len(tracers_to_test) > 1:
                result = RunnerResult(
                    method=f"{result.method} ({tracer_display})",
                    tests_run=result.tests_run,
                    differences_found=result.differences_found,
                )

            results.append(result)

    return results
