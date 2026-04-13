"""Tests for __main__.py CLI helpers (pure functions only).

`run()` orchestrates network + runners and is exercised via the integration
test in tests/test_runners_integration.py; here we cover the pure helpers
that build context, parse flags, resolve paths, and summarize results.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from json_rpc_scan.__main__ import (
    build_context,
    build_parser,
    build_trace_config,
    get_methods_for_namespaces,
    get_output_dir,
    list_methods,
    load_config,
    print_summary,
)


class TestBuildParser:
    def test_defaults(self):
        parser = build_parser()
        args = parser.parse_args([])
        assert args.start_block == 0
        assert args.end_block is None
        assert args.namespace is None
        assert args.methods is None
        assert args.tracer is None
        assert args.skip_compat_check is False
        assert args.timeout == 60.0
        assert args.concurrent == 10
        assert args.config == Path("config.yaml")

    def test_positional_endpoints(self):
        parser = build_parser()
        args = parser.parse_args(["http://a", "http://b"])
        assert args.endpoints == ["http://a", "http://b"]

    def test_namespace_and_methods(self):
        parser = build_parser()
        args = parser.parse_args(["--namespace", "eth", "--methods", "eth_call"])
        assert args.namespace == "eth"
        assert args.methods == "eth_call"

    def test_no_state_override_flag(self):
        parser = build_parser()
        args = parser.parse_args(["--no-state-override"])
        assert args.no_state_override is True


class TestLoadConfig:
    def test_loads_yaml_if_file_exists(self, tmp_path):
        cfg_path = tmp_path / "config.yaml"
        cfg_path.write_text(
            "endpoints:\n"
            "  - name: Geth\n"
            "    url: http://geth:8545\n"
            "  - name: Nethermind\n"
            "    url: http://neth:8545\n"
        )
        args = argparse.Namespace(config=cfg_path, endpoints=[])
        config = load_config(args)
        assert config is not None
        assert config.endpoints[0].name == "Geth"
        assert config.endpoints[1].url == "http://neth:8545"

    def test_falls_back_to_positional_urls(self, tmp_path):
        # No config file at this path
        args = argparse.Namespace(
            config=tmp_path / "missing.yaml",
            endpoints=["http://a", "http://b"],
        )
        config = load_config(args)
        assert config is not None
        assert config.endpoints[0].url == "http://a"
        assert config.endpoints[1].url == "http://b"

    def test_returns_none_with_neither(self, tmp_path):
        args = argparse.Namespace(
            config=tmp_path / "missing.yaml",
            endpoints=[],
        )
        assert load_config(args) is None

    def test_returns_none_with_one_url(self, tmp_path):
        args = argparse.Namespace(
            config=tmp_path / "missing.yaml",
            endpoints=["http://a"],
        )
        assert load_config(args) is None

    def test_returns_none_on_yaml_error(self, tmp_path):
        cfg_path = tmp_path / "bad.yaml"
        cfg_path.write_text("not: valid: yaml: :::")
        args = argparse.Namespace(config=cfg_path, endpoints=[])
        assert load_config(args) is None


class TestBuildTraceConfig:
    def _args(self, **overrides):
        base = argparse.Namespace(
            tracer=None,
            tracer_config=None,
            trace_timeout=None,
        )
        for k, v in overrides.items():
            setattr(base, k, v)
        return base

    def test_defaults(self):
        cfg = build_trace_config(self._args())
        assert cfg is not None
        assert cfg.tracer is None
        assert cfg.tracer_config is None

    def test_tracer_config_json_parsed(self):
        cfg = build_trace_config(self._args(tracer_config='{"onlyTopCall": true}'))
        assert cfg is not None
        assert cfg.tracer_config == {"onlyTopCall": True}

    def test_invalid_tracer_config_returns_none(self):
        assert build_trace_config(self._args(tracer_config="not json")) is None

    def test_structlogger_alias_becomes_none(self):
        cfg = build_trace_config(self._args(tracer="structLogger"))
        assert cfg is not None
        assert cfg.tracer is None

    @pytest.mark.parametrize("alias", ["struct", "opcode", "none", "STRUCT"])
    def test_all_struct_aliases_become_none(self, alias):
        cfg = build_trace_config(self._args(tracer=alias))
        assert cfg is not None
        assert cfg.tracer is None

    def test_non_alias_tracer_preserved(self):
        cfg = build_trace_config(self._args(tracer="callTracer"))
        assert cfg is not None
        assert cfg.tracer == "callTracer"

    def test_timeout_passed_through(self):
        cfg = build_trace_config(self._args(trace_timeout="30s"))
        assert cfg is not None
        assert cfg.timeout == "30s"


class TestGetMethodsForNamespaces:
    def test_debug_namespace(self):
        methods = get_methods_for_namespaces(["debug"])
        assert all(m.startswith("debug_") for m in methods)
        assert "debug_traceBlockByNumber" in methods

    def test_eth_namespace(self):
        methods = get_methods_for_namespaces(["eth"])
        assert all(m.startswith("eth_") for m in methods)
        assert "eth_call" in methods

    def test_trace_namespace(self):
        methods = get_methods_for_namespaces(["trace"])
        assert all(m.startswith("trace_") for m in methods)

    def test_all_namespace_returns_union(self):
        methods = get_methods_for_namespaces(["all"])
        assert any(m.startswith("debug_") for m in methods)
        assert any(m.startswith("eth_") for m in methods)
        assert any(m.startswith("trace_") for m in methods)

    def test_multiple_namespaces_concatenated(self):
        methods = get_methods_for_namespaces(["debug", "eth"])
        assert any(m.startswith("debug_") for m in methods)
        assert any(m.startswith("eth_") for m in methods)
        assert not any(m.startswith("trace_") for m in methods)

    def test_unknown_namespace_ignored(self):
        assert get_methods_for_namespaces(["unknown"]) == []

    def test_case_insensitive(self):
        methods_lower = get_methods_for_namespaces(["eth"])
        methods_upper = get_methods_for_namespaces(["ETH"])
        assert methods_lower == methods_upper


class TestGetOutputDir:
    def test_explicit_output(self, tmp_path):
        args = argparse.Namespace(output=tmp_path / "custom")
        assert get_output_dir(args) == tmp_path / "custom"

    def test_default_under_outputs_with_timestamp(self):
        args = argparse.Namespace(output=None)
        out = get_output_dir(args)
        assert out.parent.name == "outputs"
        # Timestamp format: YYYY-MM-DD_HH-MM-SS
        parts = out.name.split("_")
        assert len(parts) == 2


class TestBuildContext:
    def _args(self, tmp_path, **overrides):
        base = argparse.Namespace(
            config=tmp_path / "missing.yaml",
            endpoints=["http://a", "http://b"],
            start_block=0,
            end_block=10,
            namespace=None,
            methods=None,
            tracer=None,
            tracer_config=None,
            trace_timeout=None,
            no_state_override=False,
            skip_compat_check=False,
            output=tmp_path / "out",
            timeout=60.0,
            concurrent=10,
        )
        for k, v in overrides.items():
            setattr(base, k, v)
        return base

    def test_default_namespace_is_debug(self, tmp_path):
        ctx = build_context(self._args(tmp_path))
        assert ctx is not None
        assert ctx.namespaces == ["debug"]
        assert all(m.startswith("debug_") for m in ctx.methods)

    def test_explicit_namespace_is_honored(self, tmp_path):
        ctx = build_context(self._args(tmp_path, namespace="eth"))
        assert ctx is not None
        assert ctx.namespaces == ["eth"]

    def test_explicit_methods_infer_namespace(self, tmp_path):
        ctx = build_context(self._args(tmp_path, methods="eth_call,debug_traceCall"))
        assert ctx is not None
        # Both namespaces inferred from method prefixes
        assert "eth" in ctx.namespaces
        assert "debug" in ctx.namespaces
        assert ctx.methods == ["eth_call", "debug_traceCall"]

    def test_infer_trace_namespace(self, tmp_path):
        ctx = build_context(self._args(tmp_path, methods="trace_block"))
        assert ctx is not None
        assert ctx.namespaces == ["trace"]

    def test_all_tracers_flag_enabled_when_no_explicit_tracer(self, tmp_path):
        ctx = build_context(self._args(tmp_path))
        assert ctx.test_all_tracers is True

    def test_explicit_tracer_disables_all_tracers(self, tmp_path):
        ctx = build_context(self._args(tmp_path, tracer="callTracer"))
        assert ctx is not None
        assert ctx.test_all_tracers is False

    def test_no_state_override_flag(self, tmp_path):
        ctx = build_context(self._args(tmp_path, no_state_override=True))
        assert ctx is not None
        assert ctx.eth_call_config.test_state_override is False

    def test_returns_none_when_no_endpoints(self, tmp_path):
        args = self._args(tmp_path, endpoints=[])
        assert build_context(args) is None

    def test_output_dir_created(self, tmp_path):
        ctx = build_context(self._args(tmp_path))
        assert ctx is not None
        assert ctx.output_dir.exists()

    def test_config_overrides_applied(self, tmp_path):
        ctx = build_context(self._args(tmp_path, timeout=5.0, concurrent=2))
        assert ctx is not None
        assert ctx.config.timeout == 5.0
        assert ctx.config.max_concurrent == 2

    def test_invalid_tracer_config_bails(self, tmp_path):
        # Bad JSON in --tracer-config
        args = self._args(tmp_path, tracer_config="not json")
        assert build_context(args) is None


class TestPrintSummary:
    def test_exit_code_zero_when_no_diffs(self, tmp_path):
        results = [("eth_call", 5, 0), ("eth_getBalance", 3, 0)]
        code = print_summary(results, tmp_path / "never-existed")
        assert code == 0

    def test_exit_code_one_when_any_diff(self, tmp_path):
        results = [("eth_call", 5, 2)]
        tmp_path.mkdir(exist_ok=True)
        (tmp_path / "eth_call").mkdir()
        code = print_summary(results, tmp_path)
        assert code == 1

    def test_cleans_up_empty_output_dir(self, tmp_path):
        output_dir = tmp_path / "empty"
        output_dir.mkdir()
        assert output_dir.exists()
        code = print_summary([("method", 5, 0)], output_dir)
        assert code == 0
        assert not output_dir.exists()

    def test_preserves_output_dir_when_diffs_present(self, tmp_path):
        output_dir = tmp_path / "with-diffs"
        output_dir.mkdir()
        (output_dir / "method").mkdir()
        (output_dir / "method" / "block_1").mkdir()
        print_summary([("method", 5, 1)], output_dir)
        assert output_dir.exists()

    def test_sums_totals_across_methods(self, tmp_path, capsys):
        results = [("m1", 5, 1), ("m2", 3, 2), ("m3", 10, 0)]
        print_summary(results, tmp_path / "x")
        captured = capsys.readouterr()
        assert "18 tests" in captured.out  # 5+3+10
        assert "3 differences" in captured.out  # 1+2+0


class TestListMethods:
    def test_prints_available_methods(self, capsys):
        list_methods()
        captured = capsys.readouterr()
        # Hits the three namespace section headers and at least one method name
        assert "AVAILABLE METHODS" in captured.out
        assert "debug_traceBlockByNumber" in captured.out
        assert "eth_call" in captured.out
        assert "trace_block" in captured.out
        assert "BUILT-IN TRACERS" in captured.out
