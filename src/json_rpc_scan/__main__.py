"""JSON-RPC Scan - Compare Ethereum client responses.

This tool compares JSON-RPC responses between two Ethereum endpoints to detect
implementation differences. Supports debug, trace, and eth namespaces.

Usage:
    json-rpc-scan --config config.yaml
    json-rpc-scan http://geth:8545 http://nethermind:8545
    json-rpc-scan --end-block 1000 --namespace eth
    json-rpc-scan --methods eth_getBlockByNumber,eth_call
"""

from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from tqdm import tqdm


if TYPE_CHECKING:
    from json_rpc_scan.runners.base import RunnerResult

from json_rpc_scan.client import RPCClient
from json_rpc_scan.compat import (
    ClientInfo,
    filter_methods,
    filter_tracers,
    get_client_info,
)
from json_rpc_scan.compat import tracer_name as compat_tracer_name
from json_rpc_scan.config import Config
from json_rpc_scan.runners.debug import (
    BUILTIN_TRACERS,
    DEBUG_RUNNERS,
    TraceConfig,
    run_debug_methods,
    tracer_name,
)
from json_rpc_scan.runners.eth import (
    ETH_RUNNERS,
    EthCallConfig,
    run_eth_methods,
)
from json_rpc_scan.runners.trace import (
    TRACE_RUNNERS,
    TraceOptions,
    run_trace_methods,
)


# All available runners across namespaces
ALL_RUNNERS: dict[str, type] = {
    **DEBUG_RUNNERS,
    **ETH_RUNNERS,
    **TRACE_RUNNERS,
}


@dataclass
class ScanContext:
    """Context for a scan run."""

    config: Config
    trace_config: TraceConfig
    output_dir: Path
    methods: list[str]
    tracers: list[str | None]
    test_all_tracers: bool
    start_block: int
    end_block: int | None
    skip_compat: bool
    namespaces: list[str] = field(default_factory=lambda: ["debug"])
    eth_call_config: EthCallConfig = field(default_factory=EthCallConfig)
    trace_options: TraceOptions = field(default_factory=TraceOptions)


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser."""
    parser = argparse.ArgumentParser(
        prog="json-rpc-scan",
        description="Compare Ethereum JSON-RPC responses between two endpoints.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument(
        "endpoints",
        nargs="*",
        metavar="URL",
        help="Two endpoint URLs to compare (alternative to --config)",
    )
    parser.add_argument(
        "-c",
        "--config",
        type=Path,
        default=Path("config.yaml"),
        help="YAML config file (default: config.yaml)",
    )
    parser.add_argument(
        "--start-block",
        type=int,
        default=0,
        help="Starting block (default: 0)",
    )
    parser.add_argument(
        "--end-block",
        type=int,
        default=None,
        help="Ending block (default: latest)",
    )
    parser.add_argument(
        "-n",
        "--namespace",
        type=str,
        default=None,
        help="Namespace(s) to test: debug, eth, trace, or all (comma-separated)",
    )
    parser.add_argument(
        "-m",
        "--methods",
        type=str,
        default=None,
        help="Comma-separated methods to test (overrides --namespace)",
    )
    parser.add_argument(
        "--list-methods",
        action="store_true",
        help="List available methods and exit",
    )
    parser.add_argument(
        "--tracer",
        type=str,
        default=None,
        help="Specific tracer to use for debug methods (default: test ALL tracers)",
    )
    parser.add_argument(
        "--tracer-config",
        type=str,
        default=None,
        help="Tracer config as JSON (e.g., '{\"onlyTopCall\": true}')",
    )
    parser.add_argument(
        "--trace-timeout",
        type=str,
        default=None,
        help="Trace timeout (e.g., '30s')",
    )
    parser.add_argument(
        "--test-state-override",
        action="store_true",
        default=True,
        help="Test eth_call/eth_estimateGas with state overrides (default: True)",
    )
    parser.add_argument(
        "--no-state-override",
        action="store_true",
        help="Disable state override tests for eth_call/eth_estimateGas",
    )
    parser.add_argument(
        "--skip-compat-check",
        action="store_true",
        help="Skip client compatibility checks",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help="Output directory (default: outputs/<timestamp>)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=60.0,
        help="Request timeout in seconds (default: 60)",
    )
    parser.add_argument(
        "--concurrent",
        type=int,
        default=10,
        help="Max concurrent requests (default: 10)",
    )

    return parser


def list_methods() -> None:
    """Print available methods and tracers."""
    print("=" * 60)
    print("AVAILABLE METHODS BY NAMESPACE")
    print("=" * 60)

    print("\n[debug] Debug namespace methods:")
    print("-" * 40)
    for name, runner_cls in DEBUG_RUNNERS.items():
        print(f"  {name}")
        print(f"    {runner_cls.description}")

    print("\n[eth] Eth namespace methods:")
    print("-" * 40)
    for name, runner_cls in ETH_RUNNERS.items():
        print(f"  {name}")
        print(f"    {runner_cls.description}")

    print("\n[trace] Trace namespace methods (Nethermind/Erigon/Reth only):")
    print("-" * 40)
    for name, runner_cls in TRACE_RUNNERS.items():
        print(f"  {name}")
        print(f"    {runner_cls.description}")

    print("\n" + "=" * 60)
    print("BUILT-IN TRACERS (for debug methods)")
    print("=" * 60)
    for tracer in BUILTIN_TRACERS:
        print(f"  - {tracer_name(tracer)}")

    print("\n" + "=" * 60)
    print("USAGE EXAMPLES")
    print("=" * 60)
    print("  # Test all eth methods:")
    print("  json-rpc-scan --namespace eth --end-block 1000")
    print()
    print("  # Test specific methods:")
    print("  json-rpc-scan --methods eth_call,eth_getBalance --end-block 1000")
    print()
    print("  # Test all namespaces:")
    print("  json-rpc-scan --namespace all --end-block 100")
    print()
    print("Note: Methods are auto-filtered by client compatibility.")


def load_config(args: argparse.Namespace) -> Config | None:
    """Load endpoint configuration."""
    if args.config.exists():
        try:
            return Config.from_yaml(args.config)
        except Exception as e:
            tqdm.write(f"Error loading {args.config}: {e}")
            return None

    if args.endpoints and len(args.endpoints) >= 2:
        return Config.from_urls(args.endpoints[0], args.endpoints[1])

    tqdm.write("Error: Need two endpoints (via config file or command line)")
    return None


def build_trace_config(args: argparse.Namespace) -> TraceConfig | None:
    """Build trace configuration from CLI args."""
    tracer_config = None
    if args.tracer_config:
        try:
            tracer_config = json.loads(args.tracer_config)
        except json.JSONDecodeError as e:
            tqdm.write(f"Error: Invalid --tracer-config JSON: {e}")
            return None

    tracer = args.tracer
    if tracer and tracer.lower() in ("structlogger", "struct", "opcode", "none"):
        tracer = None

    return TraceConfig(
        tracer=tracer,
        tracer_config=tracer_config,
        timeout=args.trace_timeout,
    )


def get_output_dir(args: argparse.Namespace) -> Path:
    """Get output directory path."""
    if args.output:
        return Path(args.output)
    timestamp = datetime.now(UTC).strftime("%Y-%m-%d_%H-%M-%S")
    return Path("outputs") / timestamp


def get_methods_for_namespaces(namespaces: list[str]) -> list[str]:
    """Get all methods for the specified namespaces."""
    methods: list[str] = []

    for ns in namespaces:
        ns_lower = ns.lower()
        if ns_lower == "debug":
            methods.extend(DEBUG_RUNNERS.keys())
        elif ns_lower == "eth":
            methods.extend(ETH_RUNNERS.keys())
        elif ns_lower == "trace":
            methods.extend(TRACE_RUNNERS.keys())
        elif ns_lower == "all":
            methods.extend(DEBUG_RUNNERS.keys())
            methods.extend(ETH_RUNNERS.keys())
            methods.extend(TRACE_RUNNERS.keys())

    return methods


def build_context(args: argparse.Namespace) -> ScanContext | None:
    """Build scan context from CLI args."""
    config = load_config(args)
    if config is None:
        return None

    config.timeout = args.timeout
    config.max_concurrent = args.concurrent

    trace_config = build_trace_config(args)
    if trace_config is None:
        return None

    # Determine namespaces and methods
    if args.methods:
        # Explicit methods override namespace
        methods = [m.strip() for m in args.methods.split(",")]
        namespaces = []
        # Infer namespaces from methods
        for m in methods:
            if m.startswith("debug_") and "debug" not in namespaces:
                namespaces.append("debug")
            elif m.startswith("eth_") and "eth" not in namespaces:
                namespaces.append("eth")
            elif m.startswith("trace_") and "trace" not in namespaces:
                namespaces.append("trace")
    elif args.namespace:
        namespaces = [ns.strip() for ns in args.namespace.split(",")]
        methods = get_methods_for_namespaces(namespaces)
    else:
        # Default to debug namespace
        namespaces = ["debug"]
        methods = list(DEBUG_RUNNERS.keys())

    test_all_tracers = args.tracer is None
    tracers: list[str | None] = (
        list(BUILTIN_TRACERS) if test_all_tracers else [trace_config.tracer]
    )

    output_dir = get_output_dir(args)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Build eth_call config
    eth_call_config = EthCallConfig(
        test_state_override=not args.no_state_override,
    )

    return ScanContext(
        config=config,
        trace_config=trace_config,
        output_dir=output_dir,
        methods=methods,
        tracers=tracers,
        test_all_tracers=test_all_tracers,
        start_block=args.start_block,
        end_block=args.end_block,
        skip_compat=args.skip_compat_check,
        namespaces=namespaces,
        eth_call_config=eth_call_config,
    )


async def detect_and_filter(
    client: RPCClient,
    ctx: ScanContext,
) -> tuple[ClientInfo, ClientInfo, list[str], list[str | None]] | None:
    """Detect clients and filter methods/tracers by compatibility."""
    print("Detecting client types...")
    client1, client2 = await asyncio.gather(
        get_client_info(client, ctx.config.endpoints[0]),
        get_client_info(client, ctx.config.endpoints[1]),
    )

    print(f"Endpoint 1: {client1.name} ({ctx.config.endpoints[0].url})")
    print(f"  Version: {client1.version_string}")
    print(f"Endpoint 2: {client2.name} ({ctx.config.endpoints[1].url})")
    print(f"  Version: {client2.version_string}")
    print()

    ctx.config.endpoints[0].name = client1.name
    ctx.config.endpoints[1].name = client2.name

    if ctx.skip_compat:
        return client1, client2, ctx.methods, ctx.tracers

    overrides = ctx.config.compat_overrides
    methods, skipped_m = filter_methods(client1, client2, ctx.methods, overrides)
    tracers, skipped_t = filter_tracers(client1, client2, ctx.tracers, overrides)

    if skipped_m:
        print("Skipped methods (incompatible):", ", ".join(skipped_m))
    if skipped_t:
        skipped_names = [compat_tracer_name(t) for t in skipped_t]
        print("Skipped tracers (incompatible):", ", ".join(skipped_names))
    if skipped_m or skipped_t:
        print()

    if not methods:
        print("Error: No compatible methods to test")
        return None

    # For non-debug namespaces, tracers aren't needed
    has_debug = any(m.startswith("debug_") for m in methods)
    if not has_debug:
        tracers = [None]  # Placeholder

    if has_debug and not tracers:
        print("Error: No compatible tracers for debug methods")
        return None

    return client1, client2, methods, tracers


def print_summary(results: list[tuple[str, int, int]], output_dir: Path) -> int:
    """Print results summary and return exit code."""
    total_tests = sum(r[1] for r in results)
    total_diffs = sum(r[2] for r in results)

    print()
    print("=" * 60)
    print("RESULTS")
    print("=" * 60)

    for method, tests, diffs in results:
        icon = "✓" if diffs == 0 else "✗"
        print(f"  {icon} {method}: {tests} tests, {diffs} diffs")

    print("-" * 60)
    print(f"  Total: {total_tests} tests, {total_diffs} differences")
    print()

    if output_dir.exists() and not any(output_dir.iterdir()):
        shutil.rmtree(output_dir)
        print("No differences found.")
    elif total_diffs > 0:
        print(f"Diff reports: {output_dir}")

    return 1 if total_diffs > 0 else 0


async def run(args: argparse.Namespace) -> int:
    """Run the scan."""
    ctx = build_context(args)
    if ctx is None:
        return 1

    async with RPCClient(
        timeout=ctx.config.timeout,
        max_concurrent=ctx.config.max_concurrent,
    ) as rpc_client:
        result = await detect_and_filter(rpc_client, ctx)
        if result is None:
            return 1
        _, _, methods, tracers = result

        print(f"Output: {ctx.output_dir}")
        print(f"Namespaces: {', '.join(ctx.namespaces)}")
        print(f"Methods: {len(methods)}")

        # Only show tracers for debug methods
        debug_methods = [m for m in methods if m.startswith("debug_")]
        if debug_methods and ctx.test_all_tracers:
            print(f"Tracers: {', '.join(tracer_name(t) for t in tracers)}")
        print()

        end_block = ctx.end_block
        if end_block is None:
            print("Fetching latest block...")
            end_block = await rpc_client.get_block_number(ctx.config.endpoints[0])
            if end_block is None:
                tqdm.write("Error: Could not get latest block number")
                return 1

        print(f"Block range: {ctx.start_block} → {end_block}")
        print()

        all_results: list[RunnerResult] = []

        # Run debug methods
        debug_methods = [m for m in methods if m.startswith("debug_")]
        if debug_methods:
            print("=" * 60)
            print("DEBUG NAMESPACE")
            print("=" * 60)
            results = await run_debug_methods(
                client=rpc_client,
                endpoints=ctx.config.endpoints,
                output_dir=ctx.output_dir / "debug",
                start_block=ctx.start_block,
                end_block=end_block,
                trace_config=ctx.trace_config,
                methods=debug_methods,
                test_all_tracers=ctx.test_all_tracers,
                tracers=tracers if ctx.test_all_tracers else None,
            )
            all_results.extend(results)

        # Run eth methods
        eth_methods = [m for m in methods if m.startswith("eth_")]
        if eth_methods:
            print("=" * 60)
            print("ETH NAMESPACE")
            print("=" * 60)
            results = await run_eth_methods(
                client=rpc_client,
                endpoints=ctx.config.endpoints,
                output_dir=ctx.output_dir / "eth",
                start_block=ctx.start_block,
                end_block=end_block,
                methods=eth_methods,
                eth_call_config=ctx.eth_call_config,
            )
            all_results.extend(results)

        # Run trace methods
        trace_methods = [m for m in methods if m.startswith("trace_")]
        if trace_methods:
            print("=" * 60)
            print("TRACE NAMESPACE")
            print("=" * 60)
            results = await run_trace_methods(
                client=rpc_client,
                endpoints=ctx.config.endpoints,
                output_dir=ctx.output_dir / "trace",
                start_block=ctx.start_block,
                end_block=end_block,
                trace_options=ctx.trace_options,
                methods=trace_methods,
            )
            all_results.extend(results)

    return print_summary(
        [(r.method, r.tests_run, r.differences_found) for r in all_results],
        ctx.output_dir,
    )


def main() -> int:
    """CLI entry point."""
    parser = build_parser()
    args = parser.parse_args()

    if args.list_methods:
        list_methods()
        return 0

    return asyncio.run(run(args))


if __name__ == "__main__":
    sys.exit(main())
