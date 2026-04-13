# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with
code in this repository.

## Project

`json-rpc-scan` is a CLI tool that compares JSON-RPC responses between two
Ethereum execution clients (Geth, Nethermind, Erigon, Besu, Reth, Nimbus,
Ethrex) to detect implementation differences across the `debug`, `eth`, and
`trace` namespaces. Python 3.13+, fully async (`httpx`), typed
(`mypy --strict`).

## Common commands

Environment uses `uv` + `direnv`. The `.envrc` auto-activates a `.venv` on
`cd`; if not using direnv, run `uv sync --all-extras` and
`source .venv/bin/activate`.

```bash
# Tests
pytest                                         # full suite
pytest tests/test_diff.py                      # single file
pytest tests/test_diff.py::test_name           # single test
pytest -m "not slow"                           # skip slow/integration
pytest --cov                                   # with coverage (fails below 80%)

# Lint / format / types
ruff check src/ tests/
ruff format src/ tests/
mypy src/
pre-commit run --all-files

# Run the tool
json-rpc-scan --list-methods
json-rpc-scan --config config.yaml --namespace all --end-block 100
json-rpc-scan http://geth:8545 http://neth:8545 --methods eth_call,eth_getBalance
```

`pytest` uses `asyncio_mode = "auto"` — async test functions do not need
`@pytest.mark.asyncio`. `tests/conftest.py` autouse-stubs `asyncio.sleep` so
retry tests run instantly.

## Architecture

### Entry point and orchestration

`src/json_rpc_scan/__main__.py` is the CLI. Flow: `main()` → `build_context()`
(resolves config, methods, tracers, output dir into a `ScanContext`) →
`detect_and_filter()` (calls `web3_clientVersion` on both endpoints and narrows
the method/tracer list via `compat.py`) → dispatches to three namespace-
specific entry points (`run_debug_methods`, `run_eth_methods`,
`run_trace_methods`) → `print_summary()` deletes the output dir if nothing
diffed, returns exit code 1 iff any diffs were found.

### Runner pattern

Each JSON-RPC method is a `BaseRunner` subclass in
`src/json_rpc_scan/runners/{debug,eth,trace}.py`. Each module exports a
`*_RUNNERS: dict[method_name, RunnerClass]` registry that `__main__.py` merges
into `ALL_RUNNERS`.

Two helpers on `BaseRunner` remove boilerplate:

- `compare_one(identifier, params)` — the atomic unit: calls both endpoints,
  runs the comparator, saves a diff if they differ, returns `True` if a diff
  was written. Multi-variant runners (`eth_call`, `eth_estimateGas`,
  `debug_traceCall`) loop over variants and call `compare_one` per variant.
- `compare_over(iterable, *, total, unit)` — wraps `compare_one` in a tqdm
  loop. Simple-iterator runners become one input generator plus one call to
  this helper.

`tx_to_call_obj(tx, *, include_gas, include_gas_pricing, include_access_list)`
in `base.py` is the single implementation of tx-to-call conversion; each
runner that needs it passes appropriate flags (e.g. `eth_estimateGas` passes
`include_gas=False` because gas is what's being estimated).

### Semantic comparison layer

`comparator.py` and `normalize.py` back the comparison gate. Always-on
normalizers (safe by spec — `strip_envelope`, `lowercase_hex`) apply to every
comparison. Opt-in normalizers (`sort_logs_by_index`, `null_as_empty_bytes`)
are declared per-runner via the `extra_normalizers: ClassVar` — e.g.
`EthGetLogsRunner` declares `sort_logs_by_index` so log-order differences
don't show up as false diffs. `ResponseComparator.equal` returns a
`ComparisonResult` with `one_errored` / `both_errored` flags so a
success-vs-error outcome is surfaced distinctly (the previous
envelope-equality gate compared two empty-dict responses as equal, masking
this case). The runner passes `result.normalized1/2` to `DiffReporter`, so
written diff files reflect what the gate compared.

`DiffComputer` in `diff.py` applies the same normalizers before computing its
structural diff, so the JSON/text diff outputs line up with the gate.

### Client compatibility layer (`compat.py`)

Not every client supports every method/tracer (e.g. Besu lacks `callTracer`,
Geth lacks `trace_*`). `compat.py` regex-matches `web3_clientVersion` output
to a `ClientType`, then `filter_methods()` / `filter_tracers()` remove
unsupported entries before the scan runs. The YAML config's `compatibility:`
block (`skip_methods`, `skip_tracers`, `force_methods`, `force_tracers`)
overrides this matrix — essential when adding support for a new client or
working around a known broken method.

### Transport retry

`RPCClient.call` does exponential-backoff retry for `httpx.RequestError` and
5xx `HTTPStatusError`. 4xx is never retried (client bug, not transient).
Configurable via `--max-retries` and `--retry-base-delay` (defaults: 3, 0.5s).

### Config (`config.py`)

`Config.from_yaml()` and `Config.from_urls()` are the two construction paths;
CLI args can supply raw URLs when no YAML file exists. `compat_overrides` is
parsed from the YAML `compatibility:` section.

### Output

Diffs are written under `outputs/<timestamp>/<namespace>/<method>/...` (both
human-readable and machine-readable). `print_summary()` removes empty output
dirs so a clean run leaves no artifacts.

## Release process

`release-please` in manifest mode (`.release-please-config.json`,
`.release-please-manifest.json`) drives versioning from Conventional Commits.
Merging a release PR publishes to PyPI and pushes a Docker image to
`ghcr.io/MysticRyuujin/json-rpc-scan`. Commit messages must follow
Conventional Commits (enforced by `commitizen` commit-msg hook);
`no-commit-to-branch` blocks direct commits to `main`.
