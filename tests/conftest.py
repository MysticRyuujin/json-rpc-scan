"""Pytest configuration and fixtures."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest


@pytest.fixture
def anyio_backend() -> str:
    """Configure anyio backend for async tests."""
    return "asyncio"


@pytest.fixture(autouse=True)
def _no_sleep():
    """Stub out asyncio.sleep so retry tests run instantly.

    RPCClient.call performs exponential backoff on failure — the total
    wait for 3 retries is 3.5 seconds per endpoint. Multiplied across
    hundreds of runner tests that simulate RPC errors, that's unusable.
    We replace it with an instant no-op for the duration of each test.
    """
    with patch("asyncio.sleep", AsyncMock()):
        yield
