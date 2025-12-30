"""Tests for client compatibility detection."""

from json_rpc_scan.compat import (
    ClientInfo,
    ClientType,
    CompatOverrides,
    detect_client_type,
    filter_methods,
    filter_tracers,
    is_method_supported,
    is_tracer_supported,
    tracer_name,
)


class TestClientDetection:
    """Tests for client type detection from version strings."""

    def test_detect_geth(self):
        """Detect Geth client."""
        result = detect_client_type("Geth/v1.13.0-stable/linux-amd64/go1.21.0")
        assert result.client_type == ClientType.GETH
        assert result.name == "Geth"

    def test_detect_nethermind(self):
        """Detect Nethermind client."""
        result = detect_client_type("Nethermind/v1.20.0/linux-x64/dotnet7.0.9")
        assert result.client_type == ClientType.NETHERMIND
        assert result.name == "Nethermind"

    def test_detect_erigon(self):
        """Detect Erigon client."""
        result = detect_client_type("erigon/2.48.0/linux-amd64/go1.20.6")
        assert result.client_type == ClientType.ERIGON
        assert result.name == "Erigon"

    def test_detect_besu(self):
        """Detect Besu client."""
        result = detect_client_type("besu/v23.7.0/linux-x86_64/openjdk-java-17")
        assert result.client_type == ClientType.BESU
        assert result.name == "Besu"

    def test_detect_reth(self):
        """Detect Reth client."""
        result = detect_client_type("reth/v0.1.0-alpha.8/x86_64-unknown-linux-gnu")
        assert result.client_type == ClientType.RETH
        assert result.name == "Reth"

    def test_detect_nimbus(self):
        """Detect Nimbus client."""
        result = detect_client_type("nimbus-eth1/v0.1.0")
        assert result.client_type == ClientType.NIMBUS
        assert result.name == "Nimbus"

    def test_detect_ethrex(self):
        """Detect Ethrex client."""
        result = detect_client_type("ethrex/v0.1.0/x86_64-linux")
        assert result.client_type == ClientType.ETHREX
        assert result.name == "Ethrex"

    def test_detect_unknown(self):
        """Unknown client returns UNKNOWN type."""
        result = detect_client_type("SomeRandomClient/v1.0")
        assert result.client_type == ClientType.UNKNOWN
        assert result.name == "Unknown"

    def test_case_insensitive(self):
        """Detection is case insensitive."""
        assert detect_client_type("GETH/v1.0").client_type == ClientType.GETH
        assert detect_client_type("geth/v1.0").client_type == ClientType.GETH
        assert detect_client_type("ERIGON/v1.0").client_type == ClientType.ERIGON
        assert detect_client_type("NIMBUS/v1.0").client_type == ClientType.NIMBUS
        assert detect_client_type("ETHREX/v1.0").client_type == ClientType.ETHREX


class TestMethodSupport:
    """Tests for method support checking."""

    def test_geth_supports_debug_methods(self):
        """Geth supports all debug methods."""
        assert is_method_supported(ClientType.GETH, "debug_traceBlockByNumber")
        assert is_method_supported(ClientType.GETH, "debug_traceTransaction")

    def test_besu_supports_debug_methods(self):
        """Besu supports debug methods."""
        assert is_method_supported(ClientType.BESU, "debug_traceBlockByNumber")
        assert is_method_supported(ClientType.BESU, "debug_traceTransaction")

    def test_unknown_method_defaults_true(self):
        """Unknown methods default to supported."""
        assert is_method_supported(ClientType.GETH, "some_unknown_method")


class TestTracerSupport:
    """Tests for tracer support checking."""

    def test_geth_supports_all_tracers(self):
        """Geth supports all built-in tracers."""
        assert is_tracer_supported(ClientType.GETH, None)  # struct logger
        assert is_tracer_supported(ClientType.GETH, "callTracer")
        assert is_tracer_supported(ClientType.GETH, "prestateTracer")
        assert is_tracer_supported(ClientType.GETH, "4byteTracer")

    def test_besu_no_call_tracer(self):
        """Besu does NOT support callTracer."""
        assert is_tracer_supported(ClientType.BESU, None)  # struct logger works
        assert not is_tracer_supported(ClientType.BESU, "callTracer")
        assert not is_tracer_supported(ClientType.BESU, "prestateTracer")

    def test_nethermind_supports_all_tracers(self):
        """Nethermind supports all built-in tracers."""
        assert is_tracer_supported(ClientType.NETHERMIND, None)
        assert is_tracer_supported(ClientType.NETHERMIND, "callTracer")


class TestFiltering:
    """Tests for method/tracer filtering."""

    def test_filter_methods_both_support(self):
        """Methods supported by both clients pass through."""
        geth = ClientInfo(ClientType.GETH, "Geth/v1.0", "Geth")
        nm = ClientInfo(ClientType.NETHERMIND, "Nethermind/v1.0", "Nethermind")

        supported, skipped = filter_methods(geth, nm, ["debug_traceTransaction"])
        assert supported == ["debug_traceTransaction"]
        assert skipped == []

    def test_filter_tracers_geth_geth(self):
        """Two Geth nodes support all tracers."""
        geth1 = ClientInfo(ClientType.GETH, "Geth/v1.0", "Geth")
        geth2 = ClientInfo(ClientType.GETH, "Geth/v1.0", "Geth")

        supported, skipped = filter_tracers(
            geth1, geth2, [None, "callTracer", "prestateTracer"]
        )
        assert None in supported
        assert "callTracer" in supported
        assert skipped == []

    def test_filter_tracers_geth_besu(self):
        """Geth + Besu filters out callTracer."""
        geth = ClientInfo(ClientType.GETH, "Geth/v1.0", "Geth")
        besu = ClientInfo(ClientType.BESU, "besu/v1.0", "Besu")

        supported, skipped = filter_tracers(
            geth, besu, [None, "callTracer", "prestateTracer"]
        )
        assert None in supported  # struct logger works
        assert "callTracer" in skipped
        assert "prestateTracer" in skipped


class TestCompatOverrides:
    """Tests for compatibility overrides."""

    def test_skip_methods_override(self):
        """skip_methods removes methods even if supported."""
        geth1 = ClientInfo(ClientType.GETH, "Geth/v1.0", "Geth")
        geth2 = ClientInfo(ClientType.GETH, "Geth/v1.0", "Geth")
        overrides = CompatOverrides(skip_methods=["debug_traceTransaction"])

        supported, skipped = filter_methods(
            geth1, geth2, ["debug_traceTransaction", "debug_traceCall"], overrides
        )
        assert "debug_traceTransaction" in skipped
        assert "debug_traceCall" in supported

    def test_skip_tracers_override(self):
        """skip_tracers removes tracers even if supported."""
        geth1 = ClientInfo(ClientType.GETH, "Geth/v1.0", "Geth")
        geth2 = ClientInfo(ClientType.GETH, "Geth/v1.0", "Geth")
        overrides = CompatOverrides(skip_tracers=["callTracer"])

        supported, skipped = filter_tracers(
            geth1, geth2, [None, "callTracer", "prestateTracer"], overrides
        )
        assert "callTracer" in skipped
        assert None in supported
        assert "prestateTracer" in supported

    def test_force_methods_override(self):
        """force_methods enables methods even if not supported."""
        # Unknown clients with a method marked unsupported
        unknown1 = ClientInfo(ClientType.UNKNOWN, "Unknown/v1.0", "Unknown")
        unknown2 = ClientInfo(ClientType.UNKNOWN, "Unknown/v1.0", "Unknown")
        overrides = CompatOverrides(force_methods=["some_unsupported_method"])

        supported, _ = filter_methods(
            unknown1, unknown2, ["some_unsupported_method"], overrides
        )
        assert "some_unsupported_method" in supported

    def test_force_tracers_override(self):
        """force_tracers enables tracers even if not supported."""
        geth = ClientInfo(ClientType.GETH, "Geth/v1.0", "Geth")
        besu = ClientInfo(ClientType.BESU, "besu/v1.0", "Besu")
        # Without override, callTracer would be skipped (Besu doesn't support it)
        overrides = CompatOverrides(force_tracers=["callTracer"])

        supported, skipped = filter_tracers(geth, besu, [None, "callTracer"], overrides)
        assert "callTracer" in supported
        assert "callTracer" not in skipped

    def test_skip_struct_logger_via_override(self):
        """Can skip structLogger using its display name."""
        geth1 = ClientInfo(ClientType.GETH, "Geth/v1.0", "Geth")
        geth2 = ClientInfo(ClientType.GETH, "Geth/v1.0", "Geth")
        overrides = CompatOverrides(skip_tracers=["structLogger"])

        supported, skipped = filter_tracers(
            geth1, geth2, [None, "callTracer"], overrides
        )
        assert None in skipped
        assert "callTracer" in supported


class TestTracerName:
    """Tests for tracer name display."""

    def test_tracer_name_none(self):
        """None tracer displays as structLogger."""
        assert tracer_name(None) == "structLogger"

    def test_tracer_name_call_tracer(self):
        """Named tracer displays as-is."""
        assert tracer_name("callTracer") == "callTracer"
