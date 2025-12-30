"""Test runners for JSON-RPC methods."""

from json_rpc_scan.runners.base import BaseRunner, RunnerResult
from json_rpc_scan.runners.debug import (
    BUILTIN_TRACERS,
    DEBUG_RUNNERS,
    DebugTraceBlockByHashRunner,
    DebugTraceBlockByNumberRunner,
    DebugTraceCallRunner,
    DebugTraceTransactionRunner,
    TraceConfig,
    run_debug_methods,
    tracer_name,
)
from json_rpc_scan.runners.eth import (
    ETH_RUNNERS,
    EthCallConfig,
    EthCallRunner,
    EthEstimateGasRunner,
    EthFeeHistoryRunner,
    EthGetBalanceRunner,
    EthGetBlockByHashRunner,
    EthGetBlockByNumberRunner,
    EthGetBlockReceiptsRunner,
    EthGetCodeRunner,
    EthGetLogsRunner,
    EthGetProofRunner,
    EthGetStorageAtRunner,
    EthGetTransactionByHashRunner,
    EthGetTransactionReceiptRunner,
    run_eth_methods,
)
from json_rpc_scan.runners.trace import (
    DEFAULT_TRACE_TYPES,
    TRACE_RUNNERS,
    TRACE_TYPES,
    TraceBlockRunner,
    TraceCallManyRunner,
    TraceCallRunner,
    TraceOptions,
    TraceTransactionRunner,
    run_trace_methods,
)


__all__ = [
    # Debug namespace
    "BUILTIN_TRACERS",
    "DEBUG_RUNNERS",
    # Trace namespace (Nethermind/Erigon/Reth)
    "DEFAULT_TRACE_TYPES",
    # Eth namespace
    "ETH_RUNNERS",
    "TRACE_RUNNERS",
    "TRACE_TYPES",
    # Base
    "BaseRunner",
    "DebugTraceBlockByHashRunner",
    "DebugTraceBlockByNumberRunner",
    "DebugTraceCallRunner",
    "DebugTraceTransactionRunner",
    "EthCallConfig",
    "EthCallRunner",
    "EthEstimateGasRunner",
    "EthFeeHistoryRunner",
    "EthGetBalanceRunner",
    "EthGetBlockByHashRunner",
    "EthGetBlockByNumberRunner",
    "EthGetBlockReceiptsRunner",
    "EthGetCodeRunner",
    "EthGetLogsRunner",
    "EthGetProofRunner",
    "EthGetStorageAtRunner",
    "EthGetTransactionByHashRunner",
    "EthGetTransactionReceiptRunner",
    "RunnerResult",
    "TraceBlockRunner",
    "TraceCallManyRunner",
    "TraceCallRunner",
    "TraceConfig",
    "TraceOptions",
    "TraceTransactionRunner",
    "run_debug_methods",
    "run_eth_methods",
    "run_trace_methods",
    "tracer_name",
]
