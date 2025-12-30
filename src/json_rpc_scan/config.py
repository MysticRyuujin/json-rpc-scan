"""Configuration loading for json-rpc-scan."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import yaml

from json_rpc_scan.client import Endpoint
from json_rpc_scan.compat import CompatOverrides


if TYPE_CHECKING:
    from pathlib import Path


@dataclass
class Config:
    """Application configuration."""

    endpoints: tuple[Endpoint, Endpoint]
    timeout: float = 60.0
    max_concurrent: int = 10
    compat_overrides: CompatOverrides = field(default_factory=CompatOverrides)

    @classmethod
    def from_yaml(cls, path: Path) -> Config:
        """Load configuration from a YAML file.

        Args:
            path: Path to the YAML config file.

        Returns:
            Config instance.

        Raises:
            ValueError: If configuration is invalid.
        """
        with path.open() as f:
            data: dict[str, Any] = yaml.safe_load(f) or {}

        endpoints_data = data.get("endpoints", [])
        if len(endpoints_data) < 2:
            msg = "Config must define at least 2 endpoints"
            raise ValueError(msg)

        # We only support exactly 2 endpoints for now
        endpoints: list[Endpoint] = []
        for i, ep in enumerate(endpoints_data[:2]):
            name = ep.get("name", f"endpoint{i + 1}")
            url = ep.get("url")
            if not url:
                msg = f"Endpoint {name} missing 'url' field"
                raise ValueError(msg)
            headers = ep.get("headers")
            endpoints.append(Endpoint(name=name, url=url, headers=headers))

        settings = data.get("settings", {})

        # Load compatibility overrides
        compat_data = data.get("compatibility", {})
        compat_overrides = CompatOverrides(
            skip_methods=compat_data.get("skip_methods", []),
            skip_tracers=compat_data.get("skip_tracers", []),
            force_methods=compat_data.get("force_methods", []),
            force_tracers=compat_data.get("force_tracers", []),
        )

        return cls(
            endpoints=(endpoints[0], endpoints[1]),
            timeout=settings.get("timeout", 60.0),
            max_concurrent=settings.get("concurrent_requests", 10),
            compat_overrides=compat_overrides,
        )

    @classmethod
    def from_urls(
        cls,
        url1: str,
        url2: str,
        name1: str = "endpoint1",
        name2: str = "endpoint2",
    ) -> Config:
        """Create configuration from two URLs.

        Args:
            url1: First endpoint URL.
            url2: Second endpoint URL.
            name1: Name for first endpoint.
            name2: Name for second endpoint.

        Returns:
            Config instance.
        """
        return cls(
            endpoints=(
                Endpoint(name=name1, url=url1),
                Endpoint(name=name2, url=url2),
            )
        )


@dataclass
class ScanOptions:
    """Options for a scan run."""

    start_block: int = 0
    end_block: int | None = None
    use_latest_block: bool = False
    methods: list[str] = field(default_factory=list)
    tracer: str = "callTracer"
    tracer_config: dict[str, Any] | None = None
    output_dir: Path | None = None
