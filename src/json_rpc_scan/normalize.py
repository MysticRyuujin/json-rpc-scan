"""Normalization primitives for JSON-RPC response comparison.

These functions transform JSON-RPC responses to strip away differences that are
provably not semantically meaningful, so comparisons between clients don't
produce false positives on transport-level or formatting-level noise.

Two tiers:

1. ALWAYS_ON — safe by spec, no real client diff can hide behind them:
   - strip_envelope: drops `id` / `jsonrpc` fields
   - lowercase_hex: lowercases 0x-prefixed hex strings (spec mandates lowercase)

2. Opt-in — may mask real diffs if applied where the method's semantics don't
   guarantee the property. Runners declare these explicitly:
   - sort_logs_by_index: stable ordering for log lists
   - null_as_empty_bytes: treat `null` ≡ `"0x"` for empty-bytes methods

A Normalizer is `Callable[[dict], dict]` and must not mutate its input — it
returns a new dict if it changes anything.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any


Normalizer = Callable[[dict[str, Any]], dict[str, Any]]


# Matches 0x-prefixed hex strings. Empty "0x" also matches (valid empty-bytes).
_HEX_RE = re.compile(r"^0x[0-9a-fA-F]*$")


def strip_envelope(response: dict[str, Any]) -> dict[str, Any]:
    """Drop `id` and `jsonrpc` envelope fields.

    JSON-RPC 2.0 mandates that `jsonrpc` is always the string "2.0" and that
    `id` is echoed back — neither conveys anything about the method result.
    Differences in these fields are always spurious.
    """
    return {k: v for k, v in response.items() if k not in ("id", "jsonrpc")}


def lowercase_hex(response: dict[str, Any]) -> dict[str, Any]:
    """Recursively lowercase 0x-prefixed hex strings.

    The Ethereum JSON-RPC spec returns hex values lowercased, but some clients
    emit EIP-55 checksummed addresses (mixed case). Lowercasing throws away no
    spec-meaningful information.
    """
    return _lowercase_hex_value(response)  # type: ignore[no-any-return]


def _lowercase_hex_value(value: Any) -> Any:
    if isinstance(value, str):
        return value.lower() if _HEX_RE.match(value) else value
    if isinstance(value, dict):
        return {k: _lowercase_hex_value(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_lowercase_hex_value(v) for v in value]
    return value


def sort_logs_by_index(response: dict[str, Any]) -> dict[str, Any]:
    """Sort a log array in `result` by (blockNumber, logIndex).

    Opt-in — apply to `eth_getLogs` and anywhere else the spec says ordering is
    unspecified. Some clients return logs in emission order, others in index
    order; both are correct, so sorting makes comparison stable.
    """
    result = response.get("result")
    sorted_result = _sort_log_list(result)
    if sorted_result is result:
        return response
    return {**response, "result": sorted_result}


def _sort_log_list(value: Any) -> Any:
    if not isinstance(value, list) or not value:
        return value
    if not all(isinstance(item, dict) for item in value):
        return value

    def key(log: dict[str, Any]) -> tuple[int, int]:
        bn = log.get("blockNumber", "0x0")
        li = log.get("logIndex", "0x0")
        bn_int = int(bn, 16) if isinstance(bn, str) else int(bn or 0)
        li_int = int(li, 16) if isinstance(li, str) else int(li or 0)
        return (bn_int, li_int)

    try:
        return sorted(value, key=key)
    except (TypeError, ValueError):
        return value


def null_as_empty_bytes(response: dict[str, Any]) -> dict[str, Any]:
    """Treat `result: null` as equivalent to `result: "0x"`.

    Opt-in — apply to methods like `eth_getCode` where some clients return
    `null` for EOAs while others return `"0x"`. Semantically the same empty
    bytecode.
    """
    if response.get("result") is None and "result" in response:
        return {**response, "result": "0x"}
    return response


def apply_all(
    response: dict[str, Any],
    normalizers: list[Normalizer],
) -> dict[str, Any]:
    """Apply a list of normalizers in order."""
    for norm in normalizers:
        response = norm(response)
    return response


# Always applied by ResponseComparator and DiffComputer. Safe per the JSON-RPC /
# Ethereum JSON-RPC spec — the plan's safety argument depends on this tuple
# containing only provably-safe normalizers.
ALWAYS_ON: tuple[Normalizer, ...] = (strip_envelope, lowercase_hex)
