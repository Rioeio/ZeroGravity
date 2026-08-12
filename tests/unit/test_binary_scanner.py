from __future__ import annotations

import asyncio
import re
import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from zerogravity.scanner.binary_scanner import probe_binary, run_full_scan
from zerogravity.resolver.models import BinaryProbe


@pytest.mark.asyncio
async def test_probe_installed_binary():
    """Test probing a binary that exists in PATH and returns a version."""
    mock_proc = AsyncMock()
    mock_proc.communicate.return_value = (b"v20.11.0\n", b"")
    mock_proc.returncode = 0

    with patch("zerogravity.scanner.binary_scanner.shutil.which", return_value="/usr/bin/node"):
        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            result = await probe_binary("node", ["node", "--version"])
            assert result.installed is True
            assert result.version == "20.11.0"
            assert result.error is None


@pytest.mark.asyncio
async def test_probe_missing_binary():
    """Test probing a binary that is NOT in PATH."""
    with patch("zerogravity.scanner.binary_scanner.shutil.which", return_value=None):
        result = await probe_binary("missing_bin", ["missing_bin", "--version"])
        assert result.installed is False
        assert result.version is None


@pytest.mark.asyncio
async def test_probe_timeout():
    """Test probing a binary that times out."""
    mock_proc = AsyncMock()
    mock_proc.communicate.side_effect = asyncio.TimeoutError()

    with patch("zerogravity.scanner.binary_scanner.shutil.which", return_value="/usr/bin/slow"):
        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            with patch("asyncio.wait_for", side_effect=asyncio.TimeoutError()):
                result = await probe_binary("slow", ["slow", "--version"])
                assert result.installed is True
                assert result.version is None


def test_version_extraction_node():
    """Verify regex extracts semver from 'v20.11.0'."""
    match = re.search(r'(\d+\.\d+\.\d+)', "v20.11.0")
    assert match and match.group(1) == "20.11.0"


def test_version_extraction_python():
    """Verify regex extracts semver from 'Python 3.11.5'."""
    match = re.search(r'(\d+\.\d+\.\d+)', "Python 3.11.5")
    assert match and match.group(1) == "3.11.5"


def test_version_extraction_git():
    """Verify regex extracts semver from 'git version 2.42.0'."""
    match = re.search(r'(\d+\.\d+\.\d+)', "git version 2.42.0")
    assert match and match.group(1) == "2.42.0"


@pytest.mark.asyncio
async def test_run_full_scan():
    """Test a full scan with mocked subprocess."""
    mock_proc = AsyncMock()
    mock_proc.communicate.return_value = (b"1.0.0\n", b"")
    mock_proc.returncode = 0

    with patch("zerogravity.scanner.binary_scanner.shutil.which", return_value="/usr/bin/fake"):
        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            results = await run_full_scan(["node", "python"])
            assert "node" in results
            assert "python" in results
            assert results["node"].installed is True
