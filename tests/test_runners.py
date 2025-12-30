"""Tests for the runners module."""

from __future__ import annotations

from json_rpc_scan.runners.debug import BUILTIN_TRACERS, TraceConfig, tracer_name


class TestTraceConfig:
    """Tests for TraceConfig class."""

    def test_default_config_empty_params(self):
        """Default config (struct logger) produces empty params."""
        config = TraceConfig()
        params = config.to_params()
        assert params == {}

    def test_tracer_only(self):
        """Setting tracer without config."""
        config = TraceConfig(tracer="callTracer")
        params = config.to_params()
        assert params == {"tracer": "callTracer"}

    def test_tracer_with_config(self):
        """Setting tracer with config options."""
        config = TraceConfig(
            tracer="callTracer",
            tracer_config={"onlyTopCall": True},
        )
        params = config.to_params()
        assert params == {
            "tracer": "callTracer",
            "tracerConfig": {"onlyTopCall": True},
        }

    def test_prestate_tracer_diff_mode(self):
        """prestateTracer with diffMode config."""
        config = TraceConfig(
            tracer="prestateTracer",
            tracer_config={"diffMode": True},
        )
        params = config.to_params()
        assert params == {
            "tracer": "prestateTracer",
            "tracerConfig": {"diffMode": True},
        }

    def test_opcode_logger_options(self):
        """Opcode logger options when no tracer specified."""
        config = TraceConfig(
            enable_memory=True,
            enable_return_data=True,
        )
        params = config.to_params()
        assert params == {
            "enableMemory": True,
            "enableReturnData": True,
        }

    def test_opcode_logger_disable_options(self):
        """Opcode logger disable options."""
        config = TraceConfig(
            disable_stack=True,
            disable_storage=True,
        )
        params = config.to_params()
        assert params == {
            "disableStack": True,
            "disableStorage": True,
        }

    def test_tracer_ignores_opcode_options(self):
        """When tracer is set, opcode logger options are ignored."""
        config = TraceConfig(
            tracer="callTracer",
            enable_memory=True,  # Should be ignored
        )
        params = config.to_params()
        # Only tracer should be present, not enableMemory
        assert params == {"tracer": "callTracer"}
        assert "enableMemory" not in params

    def test_timeout_option(self):
        """Timeout option is included."""
        config = TraceConfig(timeout="30s")
        params = config.to_params()
        assert params == {"timeout": "30s"}

    def test_reexec_option(self):
        """Reexec option is included."""
        config = TraceConfig(reexec=256)
        params = config.to_params()
        assert params == {"reexec": 256}

    def test_full_config(self):
        """Full config with tracer and general options."""
        config = TraceConfig(
            tracer="callTracer",
            tracer_config={"withLog": True},
            timeout="60s",
            reexec=128,
        )
        params = config.to_params()
        assert params == {
            "tracer": "callTracer",
            "tracerConfig": {"withLog": True},
            "timeout": "60s",
            "reexec": 128,
        }

    def test_with_tracer_creates_new_config(self):
        """with_tracer creates a new config with different tracer."""
        original = TraceConfig(tracer="callTracer", timeout="30s")
        new_config = original.with_tracer("prestateTracer")

        # Original unchanged
        assert original.tracer == "callTracer"

        # New config has new tracer but preserves other options
        assert new_config.tracer == "prestateTracer"
        assert new_config.timeout == "30s"

    def test_with_tracer_clears_config_for_different_tracer(self):
        """with_tracer clears tracer_config when changing tracer."""
        original = TraceConfig(
            tracer="callTracer",
            tracer_config={"onlyTopCall": True},
        )
        new_config = original.with_tracer("prestateTracer")

        # tracer_config should be cleared for different tracer
        assert new_config.tracer_config is None

    def test_with_tracer_preserves_config_for_same_tracer(self):
        """with_tracer preserves tracer_config when tracer is the same."""
        original = TraceConfig(
            tracer="callTracer",
            tracer_config={"onlyTopCall": True},
        )
        new_config = original.with_tracer("callTracer")

        # tracer_config should be preserved
        assert new_config.tracer_config == {"onlyTopCall": True}

    def test_with_tracer_to_none(self):
        """with_tracer can set tracer to None (struct logger)."""
        original = TraceConfig(tracer="callTracer")
        new_config = original.with_tracer(None)

        assert new_config.tracer is None


class TestTracerHelpers:
    """Tests for tracer helper functions."""

    def test_tracer_name_none(self):
        """tracer_name returns 'structLogger' for None."""
        assert tracer_name(None) == "structLogger"

    def test_tracer_name_call_tracer(self):
        """tracer_name returns the tracer name as-is."""
        assert tracer_name("callTracer") == "callTracer"

    def test_tracer_name_prestate(self):
        """tracer_name works for prestateTracer."""
        assert tracer_name("prestateTracer") == "prestateTracer"


class TestBuiltinTracers:
    """Tests for BUILTIN_TRACERS constant."""

    def test_builtin_tracers_contains_none(self):
        """BUILTIN_TRACERS contains None (struct logger)."""
        assert None in BUILTIN_TRACERS

    def test_builtin_tracers_contains_call_tracer(self):
        """BUILTIN_TRACERS contains callTracer."""
        assert "callTracer" in BUILTIN_TRACERS

    def test_builtin_tracers_contains_prestate_tracer(self):
        """BUILTIN_TRACERS contains prestateTracer."""
        assert "prestateTracer" in BUILTIN_TRACERS

    def test_builtin_tracers_contains_4byte_tracer(self):
        """BUILTIN_TRACERS contains 4byteTracer."""
        assert "4byteTracer" in BUILTIN_TRACERS

    def test_builtin_tracers_has_four_items(self):
        """BUILTIN_TRACERS has exactly 4 items."""
        assert len(BUILTIN_TRACERS) == 4
