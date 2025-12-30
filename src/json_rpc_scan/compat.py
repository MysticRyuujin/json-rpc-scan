"""Client compatibility detection and filtering.

Different Ethereum clients support different JSON-RPC methods and tracers.
This module detects client type from web3_clientVersion and filters out
unsupported methods/tracers.

Known client support:
- Geth: debug_* methods, all standard tracers
- Nethermind: debug_* methods, all standard tracers
- Erigon: debug_* methods, all standard tracers
- Besu: debug_* methods, but NOT callTracer (uses different tracer names)
- Reth: debug_* methods, all standard tracers
- Nimbus: debug_* methods, all standard tracers
- Ethrex: debug_* methods, all standard tracers

Note: trace_* (Parity/OpenEthereum style) methods are NOT supported by Geth.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from json_rpc_scan.client import Endpoint, RPCClient


class ClientType(Enum):
    """Known Ethereum client types."""

    GETH = auto()
    NETHERMIND = auto()
    ERIGON = auto()
    BESU = auto()
    RETH = auto()
    NIMBUS = auto()
    ETHREX = auto()
    UNKNOWN = auto()


@dataclass
class ClientInfo:
    """Information about a detected client."""

    client_type: ClientType
    version_string: str
    name: str  # Friendly name for display

    @property
    def short_name(self) -> str:
        """Get a short name for the client."""
        return self.client_type.name.lower()


@dataclass
class CompatOverrides:
    """User-defined compatibility overrides.

    Allows users to explicitly skip certain methods or tracers,
    regardless of what the built-in compatibility matrix says.
    Useful for testing unknown clients or working around known issues.
    """

    # Methods to always skip (regardless of client support)
    skip_methods: list[str] = field(default_factory=list)
    # Tracers to always skip (regardless of client support)
    skip_tracers: list[str] = field(default_factory=list)
    # Methods to force-enable (override "not supported" detection)
    force_methods: list[str] = field(default_factory=list)
    # Tracers to force-enable (override "not supported" detection)
    force_tracers: list[str] = field(default_factory=list)


# Patterns to detect client type from web3_clientVersion
CLIENT_PATTERNS: list[tuple[re.Pattern[str], ClientType, str]] = [
    (re.compile(r"Geth", re.IGNORECASE), ClientType.GETH, "Geth"),
    (re.compile(r"Nethermind", re.IGNORECASE), ClientType.NETHERMIND, "Nethermind"),
    (re.compile(r"erigon", re.IGNORECASE), ClientType.ERIGON, "Erigon"),
    (re.compile(r"besu", re.IGNORECASE), ClientType.BESU, "Besu"),
    (re.compile(r"reth", re.IGNORECASE), ClientType.RETH, "Reth"),
    (re.compile(r"nimbus", re.IGNORECASE), ClientType.NIMBUS, "Nimbus"),
    (re.compile(r"ethrex", re.IGNORECASE), ClientType.ETHREX, "Ethrex"),
]


# Methods supported by each client
# True = supported, False = not supported
#
# Eth namespace support notes:
# - eth_getBlockReceipts: Geth uses debug_getRawReceipts instead
# - eth_getProof: Erigon needs --prune.include-commitment-history=true
# - eth_blobBaseFee: Only available post-Dencun (EIP-4844)
# - eth_call state overrides: Supported by all major clients
# - eth_call block overrides: Geth-only feature
# - eth_maxPriorityFeePerGas: All modern clients support this

# Common eth methods supported by all clients
_ETH_COMMON: dict[str, bool] = {
    "eth_getBlockByNumber": True,
    "eth_getBlockByHash": True,
    "eth_getBlockTransactionCountByNumber": True,
    "eth_getBlockTransactionCountByHash": True,
    "eth_getTransactionByHash": True,
    "eth_getTransactionByBlockHashAndIndex": True,
    "eth_getTransactionByBlockNumberAndIndex": True,
    "eth_getTransactionReceipt": True,
    "eth_getTransactionCount": True,
    "eth_getBalance": True,
    "eth_getCode": True,
    "eth_getStorageAt": True,
    "eth_call": True,
    "eth_estimateGas": True,
    "eth_createAccessList": True,
    "eth_gasPrice": True,
    "eth_maxPriorityFeePerGas": True,
    "eth_feeHistory": True,
    "eth_getLogs": True,
    "eth_chainId": True,
    "eth_blockNumber": True,
    "eth_syncing": True,
    "eth_getUncleCountByBlockHash": True,
    "eth_getUncleCountByBlockNumber": True,
    "eth_getUncleByBlockHashAndIndex": True,
    "eth_getUncleByBlockNumberAndIndex": True,
}

# Common debug methods supported by all clients
_DEBUG_COMMON: dict[str, bool] = {
    "debug_traceBlockByNumber": True,
    "debug_traceBlockByHash": True,
    "debug_traceTransaction": True,
    "debug_traceCall": True,
}

CLIENT_METHOD_SUPPORT: dict[ClientType, dict[str, bool]] = {
    ClientType.GETH: {
        **_DEBUG_COMMON,
        **_ETH_COMMON,
        # Geth: use debug_getRawReceipts instead of eth_getBlockReceipts
        "eth_getBlockReceipts": False,
        "eth_getProof": True,
        "eth_blobBaseFee": True,
    },
    ClientType.NETHERMIND: {
        **_DEBUG_COMMON,
        **_ETH_COMMON,
        "eth_getBlockReceipts": True,
        "eth_getProof": True,
        "eth_blobBaseFee": True,
    },
    ClientType.ERIGON: {
        **_DEBUG_COMMON,
        **_ETH_COMMON,
        "eth_getBlockReceipts": True,
        # Erigon requires --prune.include-commitment-history=true for eth_getProof
        "eth_getProof": True,
        "eth_blobBaseFee": True,
    },
    ClientType.BESU: {
        **_DEBUG_COMMON,
        **_ETH_COMMON,
        "eth_getBlockReceipts": True,
        "eth_getProof": True,
        "eth_blobBaseFee": True,
    },
    ClientType.RETH: {
        **_DEBUG_COMMON,
        **_ETH_COMMON,
        "eth_getBlockReceipts": True,
        "eth_getProof": True,
        "eth_blobBaseFee": True,
    },
    ClientType.NIMBUS: {
        **_DEBUG_COMMON,
        **_ETH_COMMON,
        "eth_getBlockReceipts": True,
        "eth_getProof": True,
        "eth_blobBaseFee": True,
    },
    ClientType.ETHREX: {
        **_DEBUG_COMMON,
        **_ETH_COMMON,
        "eth_getBlockReceipts": True,
        "eth_getProof": True,
        "eth_blobBaseFee": True,
    },
    ClientType.UNKNOWN: {
        # Assume all methods supported for unknown clients
        **_DEBUG_COMMON,
        **_ETH_COMMON,
        "eth_getBlockReceipts": True,
        "eth_getProof": True,
        "eth_blobBaseFee": True,
    },
}

# Tracers supported by each client
# None (struct logger) is supported by all clients
CLIENT_TRACER_SUPPORT: dict[ClientType, dict[str | None, bool]] = {
    ClientType.GETH: {
        None: True,  # struct/opcode logger
        "callTracer": True,
        "prestateTracer": True,
        "4byteTracer": True,
    },
    ClientType.NETHERMIND: {
        None: True,
        "callTracer": True,
        "prestateTracer": True,
        "4byteTracer": True,
    },
    ClientType.ERIGON: {
        None: True,
        "callTracer": True,
        "prestateTracer": True,
        "4byteTracer": True,
    },
    ClientType.BESU: {
        # Besu uses different tracer names and doesn't support standard ones
        None: True,  # struct logger works
        "callTracer": False,  # Not supported
        "prestateTracer": False,  # Not supported
        "4byteTracer": False,  # Not supported
    },
    ClientType.RETH: {
        None: True,
        "callTracer": True,
        "prestateTracer": True,
        "4byteTracer": True,
    },
    ClientType.NIMBUS: {
        None: True,
        "callTracer": True,
        "prestateTracer": True,
        "4byteTracer": True,
    },
    ClientType.ETHREX: {
        None: True,
        "callTracer": True,
        "prestateTracer": True,
        "4byteTracer": True,
    },
    ClientType.UNKNOWN: {
        # Assume all tracers for unknown clients - user can override if needed
        None: True,
        "callTracer": True,
        "prestateTracer": True,
        "4byteTracer": True,
    },
}


def tracer_name(tracer: str | None) -> str:
    """Get display name for a tracer.

    Args:
        tracer: Tracer name or None for struct logger.

    Returns:
        Display name for the tracer.
    """
    return tracer if tracer else "structLogger"


def detect_client_type(version_string: str) -> ClientInfo:
    """Detect client type from web3_clientVersion response.

    Args:
        version_string: The response from web3_clientVersion.

    Returns:
        ClientInfo with detected client type.
    """
    for pattern, client_type, name in CLIENT_PATTERNS:
        if pattern.search(version_string):
            return ClientInfo(
                client_type=client_type,
                version_string=version_string,
                name=name,
            )

    return ClientInfo(
        client_type=ClientType.UNKNOWN,
        version_string=version_string,
        name="Unknown",
    )


async def get_client_info(client: RPCClient, endpoint: Endpoint) -> ClientInfo:
    """Get client info by querying web3_clientVersion.

    Args:
        client: RPC client instance.
        endpoint: Endpoint to query.

    Returns:
        ClientInfo for the endpoint.
    """
    response = await client.call(endpoint, "web3_clientVersion")

    if response.error:
        return ClientInfo(
            client_type=ClientType.UNKNOWN,
            version_string=f"Error: {response.error}",
            name="Unknown",
        )

    version = response.response.get("result", "")
    if not isinstance(version, str):
        version = str(version)

    return detect_client_type(version)


def is_method_supported(client_type: ClientType, method: str) -> bool:
    """Check if a method is supported by the client.

    Args:
        client_type: The client type.
        method: The method name.

    Returns:
        True if supported, False otherwise.
    """
    support = CLIENT_METHOD_SUPPORT.get(client_type, {})
    return support.get(method, True)  # Default to True for unknown methods


def is_tracer_supported(client_type: ClientType, tracer: str | None) -> bool:
    """Check if a tracer is supported by the client.

    Args:
        client_type: The client type.
        tracer: The tracer name (None for struct logger).

    Returns:
        True if supported, False otherwise.
    """
    support = CLIENT_TRACER_SUPPORT.get(client_type, {})
    return support.get(tracer, True)  # Default to True for unknown tracers


def filter_methods(
    client1: ClientInfo,
    client2: ClientInfo,
    methods: list[str],
    overrides: CompatOverrides | None = None,
) -> tuple[list[str], list[str]]:
    """Filter methods to only those supported by both clients.

    Args:
        client1: First client info.
        client2: Second client info.
        methods: List of methods to filter.
        overrides: Optional user-defined compatibility overrides.

    Returns:
        Tuple of (supported_methods, skipped_methods).
    """
    overrides = overrides or CompatOverrides()
    supported = []
    skipped = []

    for method in methods:
        # Check user overrides first
        if method in overrides.skip_methods:
            skipped.append(method)
            continue

        if method in overrides.force_methods:
            supported.append(method)
            continue

        # Check client compatibility
        if is_method_supported(client1.client_type, method) and is_method_supported(
            client2.client_type, method
        ):
            supported.append(method)
        else:
            skipped.append(method)

    return supported, skipped


def filter_tracers(
    client1: ClientInfo,
    client2: ClientInfo,
    tracers: list[str | None],
    overrides: CompatOverrides | None = None,
) -> tuple[list[str | None], list[str | None]]:
    """Filter tracers to only those supported by both clients.

    Args:
        client1: First client info.
        client2: Second client info.
        tracers: List of tracers to filter.
        overrides: Optional user-defined compatibility overrides.

    Returns:
        Tuple of (supported_tracers, skipped_tracers).
    """
    overrides = overrides or CompatOverrides()
    supported: list[str | None] = []
    skipped: list[str | None] = []

    for tracer in tracers:
        tracer_str = tracer or "structLogger"

        # Check user overrides first
        if tracer_str in overrides.skip_tracers:
            skipped.append(tracer)
            continue

        if tracer_str in overrides.force_tracers:
            supported.append(tracer)
            continue

        # Check client compatibility
        if is_tracer_supported(client1.client_type, tracer) and is_tracer_supported(
            client2.client_type, tracer
        ):
            supported.append(tracer)
        else:
            skipped.append(tracer)

    return supported, skipped
