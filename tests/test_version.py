"""Tests for version information."""

from json_rpc_scan import __version__


def test_version():
    """Test that version is a valid string."""
    assert isinstance(__version__, str)
    assert len(__version__) > 0


def test_version_format():
    """Test that version follows semver format."""
    parts = __version__.split(".")
    assert len(parts) >= 2  # At least major.minor
    assert all(part.isdigit() or "-" in part for part in parts[:3])
