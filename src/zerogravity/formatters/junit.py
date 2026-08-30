"""
JUnit XML Formatter for CI test-runner integration.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from xml.dom import minidom

from zerogravity.parsers.base import ProjectManifest
from zerogravity.resolver.models import ResolutionReport, Severity
from zerogravity.security.models import SecurityReport, VulnerabilitySeverity


def format_junit(
    report: ResolutionReport,
    security_report: SecurityReport | None = None,
    manifests: list[ProjectManifest] | None = None,
) -> str:
    """
    Generate JUnit XML string from resolution and security reports.
    """
    testsuites_el = ET.Element("testsuites", name="ZeroGravity")

    total_tests = 0
    total_failures = 0
    total_errors = 0

    # 1. Dependency Resolution TestSuite
    suite_issues = ET.SubElement(testsuites_el, "testsuite", name="DependencyAudit")
    issue_tests = 0
    issue_failures = 0
    issue_errors = 0

    if not report.issues:
        # One passing testcase representing clean audit
        tc = ET.SubElement(suite_issues, "testcase", classname="zerogravity.audit", name="dependency_checks_clean")
        issue_tests += 1
    else:
        for idx, issue in enumerate(report.issues, 1):
            issue_tests += 1
            test_name = f"{issue.category.value}_{issue.affected_binary or 'check'}_{idx}"
            tc = ET.SubElement(
                suite_issues,
                "testcase",
                classname=f"zerogravity.audit.{issue.category.value}",
                name=test_name,
            )

            if issue.severity == Severity.ERROR:
                issue_errors += 1
                err = ET.SubElement(
                    tc,
                    "error",
                    message=issue.message,
                    type=issue.category.value,
                )
                err.text = f"{issue.message}\nRemediation: {issue.remediation}"
            elif issue.severity in (Severity.WARNING, Severity.INFO):
                issue_failures += 1
                fail = ET.SubElement(
                    tc,
                    "failure",
                    message=issue.message,
                    type=issue.category.value,
                )
                fail.text = f"{issue.message}\nRemediation: {issue.remediation}"

    suite_issues.set("tests", str(issue_tests))
    suite_issues.set("failures", str(issue_failures))
    suite_issues.set("errors", str(issue_errors))
    suite_issues.set("skipped", "0")

    total_tests += issue_tests
    total_failures += issue_failures
    total_errors += issue_errors

    # 2. Security Vulnerability TestSuite
    if security_report is not None:
        suite_sec = ET.SubElement(testsuites_el, "testsuite", name="SecurityAudit")
        sec_tests = 0
        sec_failures = 0
        sec_errors = 0

        if not security_report.advisories:
            tc = ET.SubElement(suite_sec, "testcase", classname="zerogravity.security", name="vulnerability_checks_clean")
            sec_tests += 1
        else:
            for idx, adv in enumerate(security_report.advisories, 1):
                sec_tests += 1
                test_name = f"{adv.package_name}@{adv.installed_version}_{adv.id}"
                tc = ET.SubElement(
                    suite_sec,
                    "testcase",
                    classname="zerogravity.security",
                    name=test_name,
                )

                if adv.severity in (VulnerabilitySeverity.CRITICAL, VulnerabilitySeverity.HIGH):
                    sec_errors += 1
                    err = ET.SubElement(
                        tc,
                        "error",
                        message=f"{adv.severity.value}: {adv.summary}",
                        type=adv.id,
                    )
                    err.text = f"{adv.summary}\nCVE: {adv.cve_id or 'N/A'}\nDetails: {adv.details}"
                else:
                    sec_failures += 1
                    fail = ET.SubElement(
                        tc,
                        "failure",
                        message=f"{adv.severity.value}: {adv.summary}",
                        type=adv.id,
                    )
                    fail.text = f"{adv.summary}\nCVE: {adv.cve_id or 'N/A'}\nDetails: {adv.details}"

        suite_sec.set("tests", str(sec_tests))
        suite_sec.set("failures", str(sec_failures))
        suite_sec.set("errors", str(sec_errors))
        suite_sec.set("skipped", "0")

        total_tests += sec_tests
        total_failures += sec_failures
        total_errors += sec_errors

    testsuites_el.set("tests", str(total_tests))
    testsuites_el.set("failures", str(total_failures))
    testsuites_el.set("errors", str(total_errors))
    testsuites_el.set("skipped", "0")

    xml_str = ET.tostring(testsuites_el, encoding="utf-8")
    parsed = minidom.parseString(xml_str)
    return parsed.toprettyxml(indent="  ", encoding="utf-8").decode("utf-8")
