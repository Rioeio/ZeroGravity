from __future__ import annotations

import io
import json
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from zerogravity.cli import app
from zerogravity.parsers.base import Dependency, DependencyType, Ecosystem, ProjectManifest
from zerogravity.security.models import VulnerabilitySeverity
from zerogravity.security.osv_client import OSVClient
from zerogravity.security.scanner import scan_vulnerabilities

runner = CliRunner()


def test_osv_query_batch_mock(tmp_path: Path):
    """Test OSV.dev batch query and vulnerability advisory parsing."""
    client = OSVClient(cache_file=tmp_path / "osv_cache.json")

    queries = [
        {"package": {"name": "lodash", "ecosystem": "npm"}, "version": "4.17.15"},
    ]

    mock_response_data = {
        "results": [
            {
                "vulns": [
                    {
                        "id": "GHSA-p6mc-m468-83gw",
                        "summary": "Prototype Pollution in lodash",
                        "aliases": ["CVE-2020-8203"],
                        "database_specific": {
                            "severity": "HIGH",
                        },
                        "severity": [
                            {"type": "CVSS_V3", "score": "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:N/I:N/A:H"}
                        ],
                    }
                ]
            }
        ]
    }

    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.read.return_value = json.dumps(mock_response_data).encode("utf-8")
    mock_resp.__enter__.return_value = mock_resp

    with patch("urllib.request.urlopen", return_value=mock_resp) as mock_urlopen:
        results = client.query_batch(queries)
        assert len(results) == 1
        assert len(results[0]) == 1
        assert results[0][0]["id"] == "GHSA-p6mc-m468-83gw"
        mock_urlopen.assert_called_once()


def test_vulnerable_fixture_surfaces_advisory(tmp_path: Path):
    """A known-vulnerable dependency version surfaces the advisory, CVE, and severity."""
    client = OSVClient(cache_file=tmp_path / "osv_cache.json")

    manifest = ProjectManifest(
        project_path=tmp_path / "app",
        project_name="vulnerable-app",
        ecosystem=Ecosystem.NODE,
        dependencies=[
            Dependency(name="lodash", version_spec="4.17.15", resolved_version="4.17.15", dep_type=DependencyType.PRODUCTION),
            Dependency(name="express", version_spec="4.18.2", resolved_version="4.18.2", dep_type=DependencyType.PRODUCTION),
        ],
    )

    mock_osv_results = [
        [
            {
                "id": "GHSA-p6mc-m468-83gw",
                "summary": "Prototype Pollution in lodash",
                "aliases": ["CVE-2020-8203"],
                "database_specific": {"severity": "HIGH"},
            }
        ],
        [],  # express has no vulnerabilities in mock
    ]

    with patch.object(client, "query_batch", return_value=mock_osv_results):
        report = scan_vulnerabilities([manifest], osv_client=client)

    assert report.total_vulnerabilities == 1
    assert report.high_count == 1
    assert report.critical_count == 0
    assert report.scanned_packages == 2

    advisory = report.advisories[0]
    assert advisory.package_name == "lodash"
    assert advisory.installed_version == "4.17.15"
    assert advisory.id == "GHSA-p6mc-m468-83gw"
    assert advisory.cve_id == "CVE-2020-8203"
    assert advisory.severity == VulnerabilitySeverity.HIGH
    assert "Prototype Pollution" in advisory.summary


def test_osv_network_failure_degrades_gracefully(tmp_path: Path):
    """Network connection errors or HTTP 500 degrade gracefully without crashing."""
    client = OSVClient(cache_file=tmp_path / "osv_cache.json")

    # 1. HTTP 500 error
    import email.message
    with patch("urllib.request.urlopen", side_effect=urllib.error.HTTPError("url", 500, "Server Error", email.message.Message(), io.BytesIO(b""))):
        results = client.query_batch([{"package": {"name": "requests", "ecosystem": "PyPI"}, "version": "2.20.0"}])
        assert results == [[]]

    # 2. Network connection error
    with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("Network unreachable")):
        manifest = ProjectManifest(
            project_path=tmp_path / "app",
            project_name="app",
            ecosystem=Ecosystem.PYTHON,
            dependencies=[
                Dependency(name="jinja2", version_spec="2.11.2", resolved_version="2.11.2", dep_type=DependencyType.PRODUCTION),
            ],
        )
        report = scan_vulnerabilities([manifest], osv_client=client)
        assert report.total_vulnerabilities == 0
        assert report.scanned_packages == 1


def test_osv_offline_mode(tmp_path: Path):
    """With offline=True, OSVClient makes zero network requests."""
    client = OSVClient(cache_file=tmp_path / "osv_cache.json")

    with patch("urllib.request.urlopen") as mock_urlopen:
        results = client.query_batch(
            [{"package": {"name": "lodash", "ecosystem": "npm"}, "version": "4.17.15"}],
            offline=True,
        )
        assert results == [[]]
        mock_urlopen.assert_not_called()


def test_cli_audit_security_command(tmp_path: Path):
    """Test zg audit-security in table and json formats."""
    proj = tmp_path / "sec_app"
    proj.mkdir()
    (proj / "package.json").write_text('{"name": "sec-app", "dependencies": {"lodash": "4.17.15"}}')

    # Table format with --offline
    result_table = runner.invoke(app, ["audit-security", str(proj), "--offline"])
    assert result_table.exit_code == 0
    assert "Security Vulnerability Audit" in result_table.stdout

    # JSON format with --offline
    result_json = runner.invoke(app, ["audit-security", str(proj), "--offline", "--format", "json"])
    assert result_json.exit_code == 0
    assert '"summary"' in result_json.stdout
    assert '"advisories"' in result_json.stdout


def test_cli_scan_with_security_summary(node_project_path: Path):
    """Test zg scan displays security summary."""
    result = runner.invoke(app, ["scan", str(node_project_path), "--offline", "--no-history"])
    assert result.exit_code == 0
    assert "Security Advisories" in result.stdout or "vulnerabilities found" in result.stdout or "scanned packages" in result.stdout
