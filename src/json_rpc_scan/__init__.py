"""JSON-RPC Scan - Compare Ethereum JSON-RPC responses between endpoints."""

from json_rpc_scan.__version__ import __version__
from json_rpc_scan.client import Endpoint, RPCClient, RPCResponse
from json_rpc_scan.compat import (
    ClientInfo,
    ClientType,
    CompatOverrides,
    detect_client_type,
    filter_methods,
    filter_tracers,
    get_client_info,
)
from json_rpc_scan.config import Config, ScanOptions
from json_rpc_scan.diff import DiffComputer, Difference, DiffReporter
from json_rpc_scan.runners.debug import TraceConfig


__all__ = [
    "ClientInfo",
    "ClientType",
    "CompatOverrides",
    "Config",
    "DiffComputer",
    "DiffReporter",
    "Difference",
    "Endpoint",
    "RPCClient",
    "RPCResponse",
    "ScanOptions",
    "TraceConfig",
    "__version__",
    "detect_client_type",
    "filter_methods",
    "filter_tracers",
    "get_client_info",
]
