from __future__ import annotations

import asyncio
import re
from unittest.mock import AsyncMock, patch

import pytest

from zerogravity.scanner.binary_scanner import probe_binary, run_full_scan


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


@pytest.mark.asyncio
async def test_probe_binary_library_fallback():
    """When shutil.which fails for a known library, probe_binary delegates to lib_detector."""
    from zerogravity.resolver.models import BinaryProbe

    lib_probe = BinaryProbe(name="libjpeg", installed=True, path="pkg-config:libjpeg", version="2.1.0")

    with patch("zerogravity.scanner.binary_scanner.shutil.which", return_value=None), \
         patch("zerogravity.scanner.binary_scanner.get_library_metadata", return_value={
             "type": "library",
             "pkg_config": "libjpeg",
             "apt": "libjpeg-dev",
             "rpm": "libjpeg-turbo-devel",
             "brew": "jpeg",
         }), \
         patch("zerogravity.scanner.lib_detector.detect_library", return_value=lib_probe):
        result = await probe_binary("libjpeg", ["libjpeg", "--version"])

    assert result.installed is True
    assert result.name == "libjpeg"
    assert result.version == "2.1.0"
    assert result.path == "pkg-config:libjpeg"


def test_compute_scoped_binaries_empty_manifests():
    """Empty manifests list resolves to exactly the baseline runtime binaries."""
    from zerogravity.scanner.binary_scanner import (
        BASELINE_RUNTIME_BINARIES,
        compute_scoped_binaries,
    )

    scoped = compute_scoped_binaries([])
    assert scoped == sorted(BASELINE_RUNTIME_BINARIES)


def test_compute_scoped_binaries_with_deps_and_engines():
    """Manifest dependencies requiring system binaries and engines are included and deduped."""
    from pathlib import Path

    from zerogravity.parsers.base import Dependency, DependencyType, Ecosystem, ProjectManifest
    from zerogravity.scanner.binary_scanner import (
        BASELINE_RUNTIME_BINARIES,
        compute_scoped_binaries,
    )

    # pillow requires: libjpeg, zlib, libpng, libtiff, libwebp
    # cryptography requires: openssl
    m1 = ProjectManifest(
        project_path=Path("/app1"),
        project_name="app1",
        ecosystem=Ecosystem.PYTHON,
        dependencies=[
            Dependency(name="pillow", version_spec=">=10.0.0", dep_type=DependencyType.PRODUCTION, source="reqs"),
            Dependency(name="cryptography", version_spec=">=41.0.0", dep_type=DependencyType.PRODUCTION, source="reqs"),
        ],
        engine_constraints={"python": ">=3.11"},
    )
    m2 = ProjectManifest(
        project_path=Path("/app2"),
        project_name="app2",
        ecosystem=Ecosystem.NODE,
        dependencies=[
            # canvas requires: pkg-config, cairo, libjpeg, libpng (overlaps with pillow)
            Dependency(name="canvas", version_spec="^2.11.2", dep_type=DependencyType.PRODUCTION, source="package.json"),
        ],
        engine_constraints={"node": ">=18.0.0", "custom-engine": ">=1.0"},
    )

    scoped = compute_scoped_binaries([m1, m2])

    for base in BASELINE_RUNTIME_BINARIES:
        assert base in scoped
    # System deps from pillow
    for dep in ["libjpeg", "zlib", "libpng", "libtiff", "libwebp", "openssl"]:
        assert dep in scoped
    # System deps from canvas
    for dep in ["pkg-config", "cairo"]:
        assert dep in scoped
    # Engine constraints
    assert "custom-engine" in scoped
    # Result must be sorted and have no duplicates
    assert scoped == sorted(set(scoped))


def test_compute_scoped_binaries_with_custom_map():
    """Custom binary map overrides in config take precedence and are included."""
    from pathlib import Path

    from zerogravity.parsers.base import Dependency, DependencyType, Ecosystem, ProjectManifest
    from zerogravity.scanner.binary_scanner import compute_scoped_binaries

    m = ProjectManifest(
        project_path=Path("/app"),
        project_name="app",
        ecosystem=Ecosystem.PYTHON,
        dependencies=[
            Dependency(name="my-lib", version_spec="1.0", dep_type=DependencyType.PRODUCTION, source="reqs"),
        ],
    )

    custom_map = {"my-lib": ["special-tool", "clang"]}
    scoped = compute_scoped_binaries([m], custom_map=custom_map)

    assert "special-tool" in scoped
    assert "clang" in scoped


@pytest.mark.asyncio
async def test_run_full_scan_clears_detection_cache():
    """run_full_scan calls clear_detection_cache before probing."""
    from zerogravity.resolver.models import BinaryProbe

    with patch("zerogravity.scanner.lib_detector.clear_detection_cache") as mock_clear, \
         patch("zerogravity.scanner.binary_scanner.probe_binary", return_value=BinaryProbe(name="node", installed=True)):
        results = await run_full_scan(["node"])
        assert mock_clear.called
        assert "node" in results
