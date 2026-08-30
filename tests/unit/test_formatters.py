from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

from typer.testing import CliRunner

from zerogravity.cli import app
from zerogravity.formatters.junit import format_junit
from zerogravity.formatters.sarif import SARIF_SCHEMA_URI, SARIF_VERSION, format_sarif
from zerogravity.parsers.base import Ecosystem
from zerogravity.resolver.models import Issue, IssueCategory, ResolutionReport, Severity
from zerogravity.security.models import (
    SecurityReport,
    VulnerabilityAdvisory,
    VulnerabilitySeverity,
)

runner = CliRunner()


def test_sarif_formatter_structure_and_schema():
    """Verify SARIF output conforms to OASIS SARIF 2.1.0 schema structure."""
    issue = Issue(
        severity=Severity.ERROR,
        category=IssueCategory.ENGINE_CONSTRAINT_VIOLATION,
        message="Node 16.0.0 required but 14.0.0 installed.",
        source_project="/tmp/project-a",
        affected_binary="node",
        expected=">=16.0.0",
        actual="14.0.0",
        remediation="Upgrade Node.js.",
    )
    report = ResolutionReport(
        issues=[issue],
        scanned_projects=1,
        scanned_binaries=5,
        timestamp=datetime.now(),
    )

    advisory = VulnerabilityAdvisory(
        id="GHSA-p6mc-m468-83gw",
        cve_id="CVE-2020-8203",
        package_name="lodash",
        installed_version="4.17.15",
        ecosystem=Ecosystem.NODE,
        summary="Prototype Pollution in lodash",
        details="A prototype pollution vulnerability exists in lodash.",
        severity=VulnerabilitySeverity.HIGH,
        project_path=Path("/tmp/project-a"),
        project_name="project-a",
    )
    security_report = SecurityReport(advisories=[advisory], scanned_packages=10)

    sarif_str = format_sarif(report, security_report=security_report)
    doc = json.loads(sarif_str)

    # Root validation
    assert doc["$schema"] == SARIF_SCHEMA_URI
    assert doc["version"] == SARIF_VERSION
    assert "runs" in doc
    assert len(doc["runs"]) == 1

    run = doc["runs"][0]
    driver = run["tool"]["driver"]
    assert driver["name"] == "ZeroGravity"
    assert "version" in driver
    assert "rules" in driver
    assert len(driver["rules"]) >= 2

    # Results validation
    results = run["results"]
    assert len(results) == 2

    # Resolution issue result
    issue_res = results[0]
    assert issue_res["ruleId"] == "ZG002"
    assert issue_res["level"] == "error"
    assert "Node 16.0.0 required" in issue_res["message"]["text"]
    assert issue_res["locations"][0]["physicalLocation"]["artifactLocation"]["uri"] == "/tmp/project-a"

    # Security advisory result
    sec_res = results[1]
    assert sec_res["ruleId"] == "ZG-SEC-HIGH"
    assert sec_res["level"] == "error"
    assert "CVE-2020-8203" in sec_res["message"]["text"]

    # Official jsonschema validation if jsonschema is installed
    try:
        import jsonschema
        # Minimal SARIF 2.1.0 JSON schema draft check
        schema = {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "type": "object",
            "required": ["$schema", "version", "runs"],
            "properties": {
                "version": {"type": "string", "enum": ["2.1.0"]},
                "runs": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["tool", "results"],
                        "properties": {
                            "tool": {
                                "type": "object",
                                "required": ["driver"],
                                "properties": {
                                    "driver": {
                                        "type": "object",
                                        "required": ["name", "rules"],
                                    }
                                },
                            },
                            "results": {"type": "array"},
                        },
                    },
                },
            },
        }
        jsonschema.validate(instance=doc, schema=schema)
    except ImportError:
        pass


def test_junit_formatter_structure_and_xml_parsing():
    """Verify JUnit XML output is well-formed XML and contains testsuites/testcases."""
    issue_warn = Issue(
        severity=Severity.WARNING,
        category=IssueCategory.MISSING_SYSTEM_DEP,
        message="Package requires openssl.",
        source_project="/tmp/proj",
        affected_binary="openssl",
        expected="installed",
        actual="missing",
        remediation="Install openssl.",
    )
    report = ResolutionReport(
        issues=[issue_warn],
        scanned_projects=1,
        scanned_binaries=5,
        timestamp=datetime.now(),
    )

    advisory = VulnerabilityAdvisory(
        id="GHSA-1234",
        cve_id="CVE-2021-9999",
        package_name="requests",
        installed_version="2.20.0",
        ecosystem=Ecosystem.PYTHON,
        summary="Security issue in requests",
        details="Details here.",
        severity=VulnerabilitySeverity.CRITICAL,
        project_path=Path("/tmp/proj"),
        project_name="proj",
    )
    sec_report = SecurityReport(advisories=[advisory], scanned_packages=5)

    junit_xml = format_junit(report, security_report=sec_report)

    # Must be parseable XML
    root = ET.fromstring(junit_xml)
    assert root.tag == "testsuites"
    assert root.attrib["name"] == "ZeroGravity"
    assert int(root.attrib["tests"]) >= 2
    assert int(root.attrib["failures"]) >= 1
    assert int(root.attrib["errors"]) >= 1

    suites = {s.attrib["name"]: s for s in root.findall("testsuite")}
    assert "DependencyAudit" in suites
    assert "SecurityAudit" in suites


def test_cli_scan_format_sarif(node_project_path: Path):
    """Test zg scan --format sarif outputs valid SARIF JSON."""
    result = runner.invoke(app, ["scan", str(node_project_path), "--format", "sarif", "--offline", "--no-history"])
    assert result.exit_code == 0
    doc = json.loads(result.stdout)
    assert doc["version"] == "2.1.0"
    assert doc["runs"][0]["tool"]["driver"]["name"] == "ZeroGravity"


def test_cli_scan_format_junit(node_project_path: Path):
    """Test zg scan --format junit outputs valid JUnit XML."""
    result = runner.invoke(app, ["scan", str(node_project_path), "--format", "junit", "--offline", "--no-history"])
    assert result.exit_code == 0
    root = ET.fromstring(result.stdout)
    assert root.tag == "testsuites"
    assert root.attrib["name"] == "ZeroGravity"


def test_cli_scan_existing_formats_untouched(node_project_path: Path):
    """Ensure existing json and table output formats continue to work identically."""
    # 1. JSON mode
    res_json = runner.invoke(app, ["scan", str(node_project_path), "--format", "json", "--offline", "--no-history"])
    assert res_json.exit_code == 0
    assert '"manifests"' in res_json.stdout
    assert '"summary"' in res_json.stdout

    # 2. Table mode
    res_table = runner.invoke(app, ["scan", str(node_project_path), "--format", "table", "--offline", "--no-history"])
    assert res_table.exit_code == 0
    assert "Project Manifests" in res_table.stdout
