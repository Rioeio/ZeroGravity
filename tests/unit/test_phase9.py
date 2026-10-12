from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path

import jsonschema
import pytest

from zerogravity.formatters.junit import format_junit
from zerogravity.formatters.sarif import format_sarif
from zerogravity.parsers.base import Ecosystem
from zerogravity.resolver.models import Issue, IssueCategory, ResolutionReport, Severity
from zerogravity.security.models import (
    SecurityReport,
    VulnerabilityAdvisory,
    VulnerabilitySeverity,
)


@pytest.fixture
def sarif_schema() -> dict:
    schema_path = Path(__file__).parent.parent / "test_fixtures" / "sarif-schema-2.1.0.json"
    return json.loads(schema_path.read_text(encoding="utf-8"))


def test_sarif_oasis_schema_validation(sarif_schema: dict) -> None:
    """Verify SARIF conforms strictly to OASIS SARIF 2.1.0 schema."""
    issues = [
        Issue(
            severity=Severity.ERROR,
            category=IssueCategory.ENGINE_CONSTRAINT_VIOLATION,
            message="Node 18.0.0 required but 16.0.0 installed.",
            source_project="/tmp/project-a",
            affected_binary="node",
            expected=">=18.0.0",
            actual="16.0.0",
        ),
        Issue(
            severity=Severity.WARNING,
            category=IssueCategory.MISSING_SYSTEM_DEP,
            message="Package requires openssl.",
            source_project="tests/test_fixtures/node_project",
            affected_binary="openssl",
        ),
        Issue(
            severity=Severity.INFO,
            category=IssueCategory.LOCKFILE_MISSING,
            message="No lockfile present.",
            source_project="",
        ),
    ]
    report = ResolutionReport(issues=issues, scanned_projects=2)

    advisory = VulnerabilityAdvisory(
        id="GHSA-1234",
        cve_id="CVE-2021-9999",
        package_name="requests",
        installed_version="2.20.0",
        ecosystem=Ecosystem.PYTHON,
        summary="Security issue in requests",
        details="Details here.",
        severity=VulnerabilitySeverity.HIGH,
        project_path=Path("/tmp/project-a"),
        project_name="project-a",
    )
    sec_report = SecurityReport(advisories=[advisory], scanned_packages=5)

    sarif_str = format_sarif(report, security_report=sec_report)
    doc = json.loads(sarif_str)

    # 1. Official OASIS schema validation
    validator = jsonschema.Draft7Validator(sarif_schema)
    errors = list(validator.iter_errors(doc))
    assert len(errors) == 0, f"SARIF schema validation errors: {[e.message for e in errors]}"

    # 2. Check rule fullDescription and driver semanticVersion
    driver = doc["runs"][0]["tool"]["driver"]
    assert "semanticVersion" in driver
    assert "version" in driver
    for rule in driver["rules"]:
        assert "fullDescription" in rule, f"Rule {rule['id']} missing fullDescription"
        assert "text" in rule["fullDescription"]

    # 3. Check ruleIndex bounds and URI format on each result
    results = doc["runs"][0]["results"]
    num_rules = len(driver["rules"])
    for res in results:
        assert "ruleIndex" in res
        assert 0 <= res["ruleIndex"] < num_rules
        loc = res["locations"][0]["physicalLocation"]["artifactLocation"]
        assert "uri" in loc
        uri = loc["uri"]
        assert not uri.startswith("\\")
        if ":" in uri and not uri.startswith("file:"):
            # Should not be raw Windows C:/
            assert not uri[1:3] == ":/"


def test_sarif_incomplete_scan_schema_validation(sarif_schema: dict) -> None:
    """Verify SARIF with incomplete execution conforms to OASIS schema."""
    report = ResolutionReport(issues=[], scanned_projects=0)
    sec_report = SecurityReport(advisories=[], scanned_packages=0, complete=False, errors=["OSV unreachable"])

    sarif_str = format_sarif(report, security_report=sec_report)
    doc = json.loads(sarif_str)

    validator = jsonschema.Draft7Validator(sarif_schema)
    errors = list(validator.iter_errors(doc))
    assert len(errors) == 0, f"SARIF schema validation errors: {[e.message for e in errors]}"

    inv = doc["runs"][0]["invocations"][0]
    assert inv["executionSuccessful"] is False
    assert len(inv["toolExecutionNotifications"]) >= 1


def test_junit_xml_attributes_and_counts() -> None:
    """Verify JUnit XML includes tests, failures, errors, skipped, and time on testsuite."""
    issue_err = Issue(
        severity=Severity.ERROR,
        category=IssueCategory.ENGINE_CONSTRAINT_VIOLATION,
        message="Critical mismatch",
    )
    issue_warn = Issue(
        severity=Severity.WARNING,
        category=IssueCategory.MISSING_SYSTEM_DEP,
        message="Warning dep",
    )
    report = ResolutionReport(issues=[issue_err, issue_warn], scanned_projects=1)

    advisory_crit = VulnerabilityAdvisory(
        id="GHSA-1",
        cve_id="CVE-1",
        package_name="pkg",
        installed_version="1.0",
        ecosystem=Ecosystem.PYTHON,
        summary="Crit",
        details="Crit details",
        severity=VulnerabilitySeverity.CRITICAL,
        project_path=Path("/tmp/p"),
        project_name="p",
    )
    sec_report = SecurityReport(advisories=[advisory_crit], scanned_packages=1)

    xml_str = format_junit(report, security_report=sec_report)
    root = ET.fromstring(xml_str)

    # Check root attributes
    assert root.tag == "testsuites"
    for attr in ("tests", "failures", "errors", "skipped", "time"):
        assert attr in root.attrib, f"Root missing attribute {attr}"

    # Check testsuite attributes
    suites = root.findall("testsuite")
    assert len(suites) == 2
    for s in suites:
        for attr in ("tests", "failures", "errors", "skipped", "time"):
            assert attr in s.attrib, f"testsuite {s.attrib.get('name')} missing attribute {attr}"

    # Check testcases
    cases = root.findall(".//testcase")
    assert len(cases) == 3
    for c in cases:
        assert "classname" in c.attrib
        assert "name" in c.attrib
        assert "time" in c.attrib
