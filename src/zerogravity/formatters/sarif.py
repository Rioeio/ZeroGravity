"""
SARIF 2.1.0 Formatter for GitHub Code Scanning and OASIS compliance.
"""

from __future__ import annotations

import json
from typing import Any

from zerogravity import __version__
from zerogravity.parsers.base import ProjectManifest
from zerogravity.resolver.models import IssueCategory, ResolutionReport, Severity
from zerogravity.security.models import SecurityReport, VulnerabilitySeverity

SARIF_SCHEMA_URI = "https://raw.githubusercontent.com/oasis-tcs/sarif-spec/master/Schemata/sarif-schema-2.1.0.json"
SARIF_VERSION = "2.1.0"

CATEGORY_TO_RULE_ID: dict[IssueCategory, str] = {
    IssueCategory.MISSING_SYSTEM_DEP: "ZG001",
    IssueCategory.ENGINE_CONSTRAINT_VIOLATION: "ZG002",
    IssueCategory.CROSS_PROJECT_CONFLICT: "ZG003",
    IssueCategory.LOCKFILE_MISSING: "ZG004",
    IssueCategory.MISSING_BINARY: "ZG005",
}

RULE_DEFINITIONS: dict[str, dict[str, Any]] = {
    "ZG001": {
        "id": "ZG001",
        "name": "MissingSystemDependency",
        "shortDescription": {"text": "A required system binary dependency is not installed on the host machine."},
        "defaultConfiguration": {"level": "warning"},
        "helpUri": "https://github.com/Rioeio/ZeroGravity",
    },
    "ZG002": {
        "id": "ZG002",
        "name": "EngineConstraintViolation",
        "shortDescription": {"text": "Project engine constraint is not satisfied by the installed runtime version."},
        "defaultConfiguration": {"level": "error"},
        "helpUri": "https://github.com/Rioeio/ZeroGravity",
    },
    "ZG003": {
        "id": "ZG003",
        "name": "CrossProjectConflict",
        "shortDescription": {"text": "Conflicting runtime engine requirements across concurrently scanned projects."},
        "defaultConfiguration": {"level": "warning"},
        "helpUri": "https://github.com/Rioeio/ZeroGravity",
    },
    "ZG004": {
        "id": "ZG004",
        "name": "LockfileMissing",
        "shortDescription": {"text": "No package lockfile was found for reproducible dependency installation."},
        "defaultConfiguration": {"level": "note"},
        "helpUri": "https://github.com/Rioeio/ZeroGravity",
    },
    "ZG005": {
        "id": "ZG005",
        "name": "MissingBinary",
        "shortDescription": {"text": "A standard development binary is missing from PATH."},
        "defaultConfiguration": {"level": "warning"},
        "helpUri": "https://github.com/Rioeio/ZeroGravity",
    },
    "ZG-SEC-CRITICAL": {
        "id": "ZG-SEC-CRITICAL",
        "name": "CriticalSecurityVulnerability",
        "shortDescription": {"text": "Critical severity security vulnerability detected in package dependency."},
        "defaultConfiguration": {"level": "error"},
        "helpUri": "https://osv.dev",
    },
    "ZG-SEC-HIGH": {
        "id": "ZG-SEC-HIGH",
        "name": "HighSecurityVulnerability",
        "shortDescription": {"text": "High severity security vulnerability detected in package dependency."},
        "defaultConfiguration": {"level": "error"},
        "helpUri": "https://osv.dev",
    },
    "ZG-SEC-MEDIUM": {
        "id": "ZG-SEC-MEDIUM",
        "name": "MediumSecurityVulnerability",
        "shortDescription": {"text": "Medium severity security vulnerability detected in package dependency."},
        "defaultConfiguration": {"level": "warning"},
        "helpUri": "https://osv.dev",
    },
    "ZG-SEC-LOW": {
        "id": "ZG-SEC-LOW",
        "name": "LowSecurityVulnerability",
        "shortDescription": {"text": "Low severity security vulnerability detected in package dependency."},
        "defaultConfiguration": {"level": "note"},
        "helpUri": "https://osv.dev",
    },
}


def _severity_to_sarif_level(severity: Severity) -> str:
    """Map internal severity to SARIF level (error, warning, note)."""
    if severity == Severity.ERROR:
        return "error"
    elif severity == Severity.WARNING:
        return "warning"
    else:
        return "note"


def _vulnerability_severity_to_sarif(severity: VulnerabilitySeverity) -> tuple[str, str]:
    """Map security severity to (rule_id, sarif_level)."""
    if severity == VulnerabilitySeverity.CRITICAL:
        return "ZG-SEC-CRITICAL", "error"
    elif severity == VulnerabilitySeverity.HIGH:
        return "ZG-SEC-HIGH", "error"
    elif severity == VulnerabilitySeverity.MEDIUM:
        return "ZG-SEC-MEDIUM", "warning"
    else:
        return "ZG-SEC-LOW", "note"


def _format_location(project_path_str: str) -> list[dict[str, Any]]:
    """Format artifact location for SARIF result."""
    uri = project_path_str.replace("\\", "/")
    if not uri:
        uri = "."
    return [
        {
            "physicalLocation": {
                "artifactLocation": {
                    "uri": uri,
                },
                "region": {
                    "startLine": 1,
                },
            }
        }
    ]


def format_sarif(
    report: ResolutionReport,
    security_report: SecurityReport | None = None,
    manifests: list[ProjectManifest] | None = None,
) -> str:
    """
    Generate valid SARIF 2.1.0 JSON string from resolution and security reports.
    """
    results: list[dict[str, Any]] = []
    used_rule_ids: set[str] = set()

    # 1. Map ResolutionReport issues
    for issue in report.issues:
        if issue.severity == Severity.OK:
            continue

        rule_id = CATEGORY_TO_RULE_ID.get(issue.category, "ZG001")
        used_rule_ids.add(rule_id)
        level = _severity_to_sarif_level(issue.severity)

        results.append({
            "ruleId": rule_id,
            "level": level,
            "message": {
                "text": issue.message,
            },
            "locations": _format_location(issue.source_project),
        })

    # 2. Map SecurityReport advisories
    if security_report:
        for adv in security_report.advisories:
            rule_id, level = _vulnerability_severity_to_sarif(adv.severity)
            used_rule_ids.add(rule_id)

            cve_str = f" ({adv.cve_id})" if adv.cve_id else ""
            msg = f"{adv.package_name}@{adv.installed_version} has {adv.severity.value} vulnerability {adv.id}{cve_str}: {adv.summary}"

            results.append({
                "ruleId": rule_id,
                "level": level,
                "message": {
                    "text": msg,
                },
                "locations": _format_location(str(adv.project_path)),
            })

    # Build active rules catalog
    rules = [
        RULE_DEFINITIONS[rid]
        for rid in sorted(used_rule_ids)
        if rid in RULE_DEFINITIONS
    ]
    if not rules:
        # Include default rule definition if no issues were reported
        rules = list(RULE_DEFINITIONS.values())[:1]

    sarif_doc = {
        "$schema": SARIF_SCHEMA_URI,
        "version": SARIF_VERSION,
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": "ZeroGravity",
                        "version": __version__,
                        "informationUri": "https://github.com/Rioeio/ZeroGravity",
                        "rules": rules,
                    }
                },
                "results": results,
            }
        ],
    }

    return json.dumps(sarif_doc, indent=2)
