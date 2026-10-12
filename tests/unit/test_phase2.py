from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

from zerogravity.cli import app
from zerogravity.formatters.sarif import format_sarif
from zerogravity.net import NetworkError
from zerogravity.parsers.base import Ecosystem
from zerogravity.resolver.models import ResolutionReport
from zerogravity.security.models import (
    SecurityReport,
    VulnerabilityAdvisory,
    VulnerabilitySeverity,
)

runner = CliRunner()


def _create_sample_node_project(proj_dir: Path) -> Path:
    proj_dir.mkdir(parents=True, exist_ok=True)
    pkg_json = {
        "name": "sample-app",
        "version": "1.0.0",
        "dependencies": {
            "lodash": "4.17.15",
        },
    }
    (proj_dir / "package.json").write_text(json.dumps(pkg_json), encoding="utf-8")
    lock_json = {
        "name": "sample-app",
        "version": "1.0.0",
        "lockfileVersion": 3,
        "packages": {
            "": {
                "name": "sample-app",
                "version": "1.0.0",
                "dependencies": {"lodash": "4.17.15"},
            },
            "node_modules/lodash": {
                "version": "4.17.15",
            },
        },
    }
    (proj_dir / "package-lock.json").write_text(json.dumps(lock_json), encoding="utf-8")
    return proj_dir


def test_exit_code_clean_below_at_threshold(tmp_path: Path):
    """Verify exit codes: 0 for clean or below threshold, 1 for at or above threshold."""
    proj = _create_sample_node_project(tmp_path / "app")

    # 1. Below threshold: MEDIUM advisory with --fail-on high -> exit 0
    med_adv = VulnerabilityAdvisory(
        id="GHSA-med-1",
        cve_id="CVE-2020-0001",
        package_name="lodash",
        installed_version="4.17.15",
        ecosystem=Ecosystem.NODE,
        summary="Medium vuln",
        details="Details",
        severity=VulnerabilitySeverity.MEDIUM,
        project_path=proj,
        project_name="sample-app",
    )
    med_report = SecurityReport(advisories=[med_adv], scanned_packages=1, complete=True)

    with patch("zerogravity.commands.security.scan_vulnerabilities", return_value=med_report):
        res = runner.invoke(app, ["audit-security", str(proj), "--fail-on", "high"])
        assert res.exit_code == 0

    # 2. At threshold: HIGH advisory with --fail-on high -> exit 1
    high_adv = VulnerabilityAdvisory(
        id="GHSA-high-1",
        cve_id="CVE-2020-0002",
        package_name="lodash",
        installed_version="4.17.15",
        ecosystem=Ecosystem.NODE,
        summary="High vuln",
        details="Details",
        severity=VulnerabilitySeverity.HIGH,
        project_path=proj,
        project_name="sample-app",
    )
    high_report = SecurityReport(advisories=[high_adv], scanned_packages=1, complete=True)

    with patch("zerogravity.commands.security.scan_vulnerabilities", return_value=high_report):
        res = runner.invoke(app, ["audit-security", str(proj), "--fail-on", "high"])
        assert res.exit_code == 1


def test_exit_code_incomplete_with_threshold_fails_closed(tmp_path: Path):
    """Unreachable OSV with --fail-on high must exit 2 (gate fails closed) and print INCOMPLETE."""
    proj = _create_sample_node_project(tmp_path / "app")

    with patch("zerogravity.net.request_json", side_effect=NetworkError("Connection refused")):
        res = runner.invoke(app, ["audit-security", str(proj), "--fail-on", "high", "--no-cache"])
        assert res.exit_code == 2
        assert "INCOMPLETE" in res.stdout


def test_exit_code_incomplete_without_threshold_exits_zero(tmp_path: Path):
    """Unreachable OSV with --fail-on none exits 0 but prints INCOMPLETE and never claims clean."""
    proj = _create_sample_node_project(tmp_path / "app")

    with patch("zerogravity.net.request_json", side_effect=NetworkError("Connection refused")):
        res = runner.invoke(app, ["audit-security", str(proj), "--fail-on", "none", "--no-cache"])
        assert res.exit_code == 0
        assert "INCOMPLETE" in res.stdout
        assert "No known vulnerabilities detected" not in res.stdout


def test_sarif_incomplete_scan_emits_failed_invocation():
    """SARIF output emits executionSuccessful=false when scan is incomplete."""
    sec_report = SecurityReport(
        advisories=[],
        scanned_packages=0,
        errors=["Network connection failed"],
        complete=False,
    )
    res_report = ResolutionReport()
    sarif_json = format_sarif(res_report, security_report=sec_report)
    sarif_data = json.loads(sarif_json)

    invocations = sarif_data["runs"][0].get("invocations", [])
    assert len(invocations) > 0
    assert invocations[0]["executionSuccessful"] is False
    assert len(invocations[0]["toolExecutionNotifications"]) > 0


def test_outdated_fail_on_threshold(tmp_path: Path):
    """Outdated command supports --fail-on-outdated with appropriate exit codes."""
    proj = _create_sample_node_project(tmp_path / "app")

    from zerogravity.outdated.models import OutdatedPackage, OutdatedReport, UpdateType

    minor_pkg = OutdatedPackage(
        name="lodash",
        current_version="4.17.0",
        latest_version="4.18.0",
        update_type=UpdateType.MINOR,
        ecosystem=Ecosystem.NODE,
        project_path=proj,
        project_name="sample-app",
    )

    # 1. Minor update with --fail-on-outdated major -> exit 0
    report_minor = OutdatedReport(packages=[minor_pkg], scanned_dependencies=1, complete=True)
    with patch("zerogravity.commands.outdated.check_outdated_dependencies", return_value=report_minor):
        res = runner.invoke(app, ["outdated", str(proj), "--fail-on-outdated", "major"])
        assert res.exit_code == 0

    # 2. Minor update with --fail-on-outdated minor -> exit 1
    with patch("zerogravity.commands.outdated.check_outdated_dependencies", return_value=report_minor):
        res = runner.invoke(app, ["outdated", str(proj), "--fail-on-outdated", "minor"])
        assert res.exit_code == 1

    # 3. Incomplete with threshold -> exit 2
    report_incomplete = OutdatedReport(packages=[], scanned_dependencies=0, complete=False, errors=["Net error"])
    with patch("zerogravity.commands.outdated.check_outdated_dependencies", return_value=report_incomplete):
        res = runner.invoke(app, ["outdated", str(proj), "--fail-on-outdated", "minor"])
        assert res.exit_code == 2


def test_unreachable_osv_repro_prints_incomplete_and_exits_2():
    """Exact EVIDENCE repro: with OSV unreachable, audit-security node_project prints INCOMPLETE and exits 2 with --fail-on high."""
    fixtures_node_proj = Path(__file__).resolve().parent.parent / "test_fixtures" / "node_project"

    with patch("zerogravity.net.request_json", side_effect=NetworkError("OSV unreachable")):
        res = runner.invoke(app, ["audit-security", str(fixtures_node_proj), "--fail-on", "high", "--no-cache"])
        assert res.exit_code == 2
        assert "INCOMPLETE" in res.stdout
