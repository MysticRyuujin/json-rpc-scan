"""Tests for the config module."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from json_rpc_scan.config import Config


if TYPE_CHECKING:
    from pathlib import Path


class TestConfig:
    """Tests for Config class."""

    def test_from_urls(self):
        """Test creating Config from URLs."""
        config = Config.from_urls(
            url1="http://host1:8545",
            url2="http://host2:8545",
            name1="Geth",
            name2="Nethermind",
        )

        assert config.endpoints[0].name == "Geth"
        assert config.endpoints[0].url == "http://host1:8545"
        assert config.endpoints[1].name == "Nethermind"
        assert config.endpoints[1].url == "http://host2:8545"

    def test_from_urls_default_names(self):
        """Test creating Config from URLs with default names."""
        config = Config.from_urls(
            url1="http://host1:8545",
            url2="http://host2:8545",
        )

        assert config.endpoints[0].name == "endpoint1"
        assert config.endpoints[1].name == "endpoint2"

    def test_from_yaml(self, tmp_path: Path):
        """Test loading Config from YAML file."""
        yaml_content = """
endpoints:
  - name: Geth
    url: http://host1:8545
  - name: Nethermind
    url: http://host2:8545

settings:
  timeout: 30
  concurrent_requests: 5
"""
        config_file = tmp_path / "config.yaml"
        config_file.write_text(yaml_content)

        config = Config.from_yaml(config_file)

        assert config.endpoints[0].name == "Geth"
        assert config.endpoints[0].url == "http://host1:8545"
        assert config.endpoints[1].name == "Nethermind"
        assert config.endpoints[1].url == "http://host2:8545"
        assert config.timeout == 30
        assert config.max_concurrent == 5

    def test_from_yaml_missing_endpoints(self, tmp_path: Path):
        """Test that YAML with fewer than 2 endpoints raises ValueError."""
        yaml_content = """
endpoints:
  - name: Geth
    url: http://host1:8545
"""
        config_file = tmp_path / "config.yaml"
        config_file.write_text(yaml_content)

        with pytest.raises(ValueError, match="at least 2 endpoints"):
            Config.from_yaml(config_file)

    def test_from_yaml_missing_url(self, tmp_path: Path):
        """Test that YAML endpoint without URL raises ValueError."""
        yaml_content = """
endpoints:
  - name: Geth
  - name: Nethermind
    url: http://host2:8545
"""
        config_file = tmp_path / "config.yaml"
        config_file.write_text(yaml_content)

        with pytest.raises(ValueError, match="missing 'url' field"):
            Config.from_yaml(config_file)

    def test_from_yaml_with_headers(self, tmp_path: Path):
        """Test loading Config from YAML with endpoint headers."""
        yaml_content = """
endpoints:
  - name: Geth
    url: http://host1:8545
    headers:
      Authorization: Bearer token123
  - name: Nethermind
    url: http://host2:8545
"""
        config_file = tmp_path / "config.yaml"
        config_file.write_text(yaml_content)

        config = Config.from_yaml(config_file)

        assert config.endpoints[0].headers == {"Authorization": "Bearer token123"}
        assert config.endpoints[1].headers is None

    def test_default_values(self):
        """Test that Config has correct default values."""
        config = Config.from_urls("http://a:8545", "http://b:8545")

        assert config.timeout == 60.0
        assert config.max_concurrent == 10
        # Default compat_overrides should be empty
        assert config.compat_overrides.skip_methods == []
        assert config.compat_overrides.skip_tracers == []
        assert config.compat_overrides.force_methods == []
        assert config.compat_overrides.force_tracers == []

    def test_from_yaml_with_compat_overrides(self, tmp_path: Path):
        """Test loading Config from YAML with compatibility overrides."""
        yaml_content = """
endpoints:
  - name: Geth
    url: http://host1:8545
  - name: Nethermind
    url: http://host2:8545

compatibility:
  skip_methods:
    - debug_traceCall
  skip_tracers:
    - prestateTracer
  force_methods:
    - debug_traceTransaction
  force_tracers:
    - callTracer
"""
        config_file = tmp_path / "config.yaml"
        config_file.write_text(yaml_content)

        config = Config.from_yaml(config_file)

        assert config.compat_overrides.skip_methods == ["debug_traceCall"]
        assert config.compat_overrides.skip_tracers == ["prestateTracer"]
        assert config.compat_overrides.force_methods == ["debug_traceTransaction"]
        assert config.compat_overrides.force_tracers == ["callTracer"]

    def test_from_yaml_without_compat_section(self, tmp_path: Path):
        """Test loading Config from YAML without compatibility section."""
        yaml_content = """
endpoints:
  - name: Geth
    url: http://host1:8545
  - name: Nethermind
    url: http://host2:8545
"""
        config_file = tmp_path / "config.yaml"
        config_file.write_text(yaml_content)

        config = Config.from_yaml(config_file)

        # Should have empty overrides
        assert config.compat_overrides.skip_methods == []
        assert config.compat_overrides.skip_tracers == []
