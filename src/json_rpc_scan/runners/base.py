"""Base class for JSON-RPC test runners."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from tqdm import tqdm

from json_rpc_scan.diff import DiffReporter


if TYPE_CHECKING:
    from pathlib import Path

    from json_rpc_scan.client import Endpoint, RPCClient


@dataclass
class RunnerResult:
    """Result from running a test runner."""

    method: str
    tests_run: int
    differences_found: int


class BaseRunner(ABC):
    """Abstract base class for test runners."""

    # Override in subclasses
    method_name: str = ""
    description: str = ""

    def __init__(
        self,
        client: RPCClient,
        endpoints: tuple[Endpoint, Endpoint],
        output_dir: Path,
    ) -> None:
        """Initialize the runner.

        Args:
            client: The RPC client to use.
            endpoints: Tuple of two endpoints to compare.
            output_dir: Directory for output files.
        """
        self.client = client
        self.endpoints = endpoints
        self.output_dir = output_dir
        self.reporter = DiffReporter(
            output_dir=output_dir,
            endpoint1_name=endpoints[0].name,
            endpoint2_name=endpoints[1].name,
        )

    @abstractmethod
    async def run(
        self,
        start_block: int,
        end_block: int,
        **kwargs: Any,
    ) -> RunnerResult:
        """Run the tests.

        Args:
            start_block: Starting block number.
            end_block: Ending block number.
            **kwargs: Additional runner-specific options.

        Returns:
            RunnerResult with statistics.
        """
        ...

    def log(self, message: str) -> None:
        """Log a message (compatible with tqdm progress bars)."""
        tqdm.write(message)
