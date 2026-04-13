# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

`json-rpc-scan` is a CLI tool that compares JSON-RPC responses between two Ethereum execution clients (Geth, Nethermind, Erigon, Besu, Reth, Nimbus, Ethrex) to detect implementation differences across the `debug`, `eth`, and `trace` namespaces. Python 3.13+, fully async (`httpx`), typed (`mypy --strict`).

## Common commands

Environment uses `uv` + `direnv`. The `.envrc` auto-activates a `.venv` on `cd`; if not using direnv, run `uv sync --all-extras` and `source .venv/bin/activate`.

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
mypy src/                                      # strict mode, configured in pyproject.toml
pre-commit run --all-files                     # runs ruff, mypy, bandit, hadolint, shellcheck, yamllint, markdownlint, gitleaks, commitizen

# Run the tool
json-rpc-scan --list-methods                   # show available methods/tracers
json-rpc-scan --config config.yaml --namespace all --end-block 100
json-rpc-scan http://geth:8545 http://neth:8545 --methods eth_call,eth_getBalance
```

`pytest` uses `asyncio_mode = "auto"` — async test functions do not need `@pytest.mark.asyncio`.

## Architecture

### Entry point and orchestration
`src/json_rpc_scan/__main__.py` is the CLI. Flow: `main()` → `build_context()` (resolves config, methods, tracers, output dir into a `ScanContext`) → `detect_and_filter()` (calls `web3_clientVersion` on both endpoints and narrows the method/tracer list via `compat.py`) → dispatches to three namespace-specific entry points (`run_debug_methods`, `run_eth_methods`, `run_trace_methods`) → `print_summary()` deletes the output dir if nothing diffed, returns exit code 1 iff any diffs were found.

### Runner pattern
Each JSON-RPC method is implemented as a `BaseRunner` subclass in `src/json_rpc_scan/runners/{debug,eth,trace}.py`. Each module exports a `*_RUNNERS: dict[method_name, RunnerClass]` registry that `__main__.py` merges into `ALL_RUNNERS`. Adding a new method = add a runner class + register it in that module's dict. Runners receive an `RPCClient`, the endpoint tuple, and an `output_dir`; they drive iteration over the block range themselves and write diffs via `DiffReporter` (`diff.py`).

Because runners exist to hit real RPC endpoints, they are excluded from coverage (`tool.coverage.run.omit` in `pyproject.toml`) and get relaxed ruff rules (`ARG002`, `PLR0912`). Unit tests for runners live in `tests/test_runners.py` and mock the client.

### Client compatibility layer (`compat.py`)
Not every client supports every method/tracer (e.g., Besu lacks `callTracer`; Geth lacks `trace_*`). `compat.py` regex-matches `web3_clientVersion` output to a `ClientType`, then `filter_methods()` / `filter_tracers()` remove unsupported entries before the scan runs. The YAML config's `compatibility:` block (`skip_methods`, `skip_tracers`, `force_methods`, `force_tracers`) overrides this matrix — essential when adding support for a new client or working around a known broken method.

### Config (`config.py`)
`Config.from_yaml()` and `Config.from_urls()` are the two construction paths; CLI args can supply raw URLs when no YAML file exists. `compat_overrides` is parsed from the YAML `compatibility:` section.

### Output
Diffs are written under `outputs/<timestamp>/<namespace>/<method>/...` (both human-readable and machine-readable). `print_summary()` removes empty output dirs so a clean run leaves no artifacts.

## Release process

`release-please` in manifest mode (`.release-please-config.json`, `.release-please-manifest.json`) drives versioning from Conventional Commits. Merging a release PR publishes to PyPI and pushes a Docker image to `ghcr.io/MysticRyuujin/json-rpc-scan`. Commit messages must follow Conventional Commits (enforced by `commitizen` commit-msg hook); `no-commit-to-branch` blocks direct commits to `main`.
