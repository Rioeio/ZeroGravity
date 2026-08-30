from __future__ import annotations

import io
import json
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from zerogravity.cli import app
from zerogravity.outdated.checker import check_outdated_dependencies, classify_update
from zerogravity.outdated.models import UpdateType
from zerogravity.outdated.registry_client import RegistryClient
from zerogravity.parsers.base import Dependency, DependencyType, Ecosystem, ProjectManifest

runner = CliRunner()


def test_classify_update():
    """Verify semantic version distance classification (major, minor, patch, up to date)."""
    assert classify_update("1.0.0", "2.0.0") == UpdateType.MAJOR
    assert classify_update("1.2.0", "1.3.0") == UpdateType.MINOR
    assert classify_update("1.2.3", "1.2.4") == UpdateType.PATCH
    assert classify_update("1.2.3", "1.2.3") == UpdateType.UP_TO_DATE
    assert classify_update("2.0.0", "1.0.0") == UpdateType.UP_TO_DATE
    assert classify_update("^1.0.0", "1.1.0") == UpdateType.MINOR
    assert classify_update("v4.18.2", "4.19.0") == UpdateType.MINOR


def test_get_latest_npm_version_mock(tmp_path: Path):
    """Test npm registry response parsing and version extraction."""
    client = RegistryClient(cache_file=tmp_path / "cache.json")
    mock_payload = json.dumps({"dist-tags": {"latest": "5.0.0"}}).encode("utf-8")

    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.read.return_value = mock_payload
    mock_resp.__enter__.return_value = mock_resp

    with patch("urllib.request.urlopen", return_value=mock_resp) as mock_urlopen:
        version = client.get_latest_npm_version("express")
        assert version == "5.0.0"
        mock_urlopen.assert_called_once()


def test_get_latest_pypi_version_mock(tmp_path: Path):
    """Test PyPI JSON API response parsing and version extraction."""
    client = RegistryClient(cache_file=tmp_path / "cache.json")
    mock_payload = json.dumps({"info": {"version": "3.1.0"}}).encode("utf-8")

    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.read.return_value = mock_payload
    mock_resp.__enter__.return_value = mock_resp

    with patch("urllib.request.urlopen", return_value=mock_resp) as mock_urlopen:
        version = client.get_latest_pypi_version("requests")
        assert version == "3.1.0"
        mock_urlopen.assert_called_once()


def test_registry_ttl_caching(tmp_path: Path):
    """Test that registry results are cached locally and respect TTL."""
    client = RegistryClient(cache_file=tmp_path / "cache.json", ttl_seconds=10)
    mock_payload = json.dumps({"info": {"version": "2.0.0"}}).encode("utf-8")

    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.read.return_value = mock_payload
    mock_resp.__enter__.return_value = mock_resp

    with patch("urllib.request.urlopen", return_value=mock_resp) as mock_urlopen:
        # First call fetches from network
        v1 = client.get_latest_pypi_version("fastapi")
        assert v1 == "2.0.0"
        assert mock_urlopen.call_count == 1

        # Second call within TTL hits cache (no network call)
        v2 = client.get_latest_pypi_version("fastapi")
        assert v2 == "2.0.0"
        assert mock_urlopen.call_count == 1

    # After expiring TTL, network is queried again
    client.ttl_seconds = -1  # force immediate expiry
    with patch("urllib.request.urlopen", return_value=mock_resp) as mock_urlopen2:
        v3 = client.get_latest_pypi_version("fastapi")
        assert v3 == "2.0.0"
        assert mock_urlopen2.call_count == 1


def test_network_failure_handled_gracefully(tmp_path: Path):
    """Network errors, 404s, and timeouts do not crash and return None gracefully."""
    client = RegistryClient(cache_file=tmp_path / "cache.json")

    # 1. HTTP 404 Error
    import email.message
    with patch("urllib.request.urlopen", side_effect=urllib.error.HTTPError("url", 404, "Not Found", email.message.Message(), io.BytesIO(b""))):
        assert client.get_latest_npm_version("nonexistent-package-xyz") is None

    # 2. Network connection error / URLError
    with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("DNS failure")):
        assert client.get_latest_pypi_version("requests") is None

    # 3. Timeout error
    with patch("urllib.request.urlopen", side_effect=TimeoutError("Connection timed out")):
        assert client.get_latest_npm_version("lodash") is None


def test_offline_mode_no_network_calls(tmp_path: Path):
    """With offline=True, no HTTP requests are made."""
    client = RegistryClient(cache_file=tmp_path / "cache.json")

    with patch("urllib.request.urlopen") as mock_urlopen:
        v_npm = client.get_latest_npm_version("lodash", offline=True)
        v_pypi = client.get_latest_pypi_version("requests", offline=True)
        assert v_npm is None
        assert v_pypi is None
        mock_urlopen.assert_not_called()


def test_check_outdated_dependencies(tmp_path: Path):
    """End-to-end check of outdated dependency calculation."""
    client = RegistryClient(cache_file=tmp_path / "cache.json")

    manifest = ProjectManifest(
        project_path=tmp_path / "app",
        project_name="app",
        ecosystem=Ecosystem.NODE,
        dependencies=[
            Dependency(name="pkg-major", version_spec="1.0.0", resolved_version="1.0.0", dep_type=DependencyType.PRODUCTION),
            Dependency(name="pkg-minor", version_spec="1.0.0", resolved_version="1.0.0", dep_type=DependencyType.PRODUCTION),
            Dependency(name="pkg-patch", version_spec="1.0.0", resolved_version="1.0.0", dep_type=DependencyType.PRODUCTION),
            Dependency(name="pkg-uptodate", version_spec="1.0.0", resolved_version="1.0.0", dep_type=DependencyType.PRODUCTION),
            Dependency(name="pkg-internal", version_spec="1.0.0", resolved_version="1.0.0", dep_type=DependencyType.PRODUCTION, metadata={"workspace_internal": True}),
        ],
    )

    registry_versions = {
        "pkg-major": "2.0.0",
        "pkg-minor": "1.1.0",
        "pkg-patch": "1.0.1",
        "pkg-uptodate": "1.0.0",
    }

    with patch.object(client, "get_latest_npm_version", side_effect=lambda name, offline=False: registry_versions.get(name)):
        report = check_outdated_dependencies([manifest], registry_client=client)

    assert report.major_count == 1
    assert report.minor_count == 1
    assert report.patch_count == 1
    assert report.total_outdated == 3
    assert len(report.packages) == 3


def test_cli_outdated_command(tmp_path: Path):
    """Test zg outdated command in table and json formats."""
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "package.json").write_text('{"name": "proj", "dependencies": {"lodash": "4.17.0"}}')

    # Run in offline mode
    result_table = runner.invoke(app, ["outdated", str(proj), "--offline"])
    assert result_table.exit_code == 0

    # Run in json format
    result_json = runner.invoke(app, ["outdated", str(proj), "--offline", "--format", "json"])
    assert result_json.exit_code == 0
    assert '"summary"' in result_json.stdout


def test_cli_scan_with_offline_flag(node_project_path: Path):
    """Test zg scan with --offline flag."""
    result = runner.invoke(app, ["scan", str(node_project_path), "--offline", "--no-history"])
    assert result.exit_code == 0
    assert "Outdated Dependencies" in result.stdout or "scanned dependencies" in result.stdout
