"""
Security scanner integrating OSV.dev batch query and vulnerability advisory extraction.
"""

from __future__ import annotations

import re
from typing import Any

from zerogravity.parsers.base import Ecosystem, ProjectManifest
from zerogravity.security.models import (
    SecurityReport,
    VulnerabilityAdvisory,
    VulnerabilitySeverity,
)
from zerogravity.security.osv_client import OSVClient


def _parse_severity(vuln: dict[str, Any]) -> tuple[VulnerabilitySeverity, str | None]:
    """Extract severity enum and CVSS score from an OSV vulnerability record."""
    db_specific = vuln.get("database_specific", {})
    raw_sev = (db_specific.get("severity") or "").strip().upper()

    cvss_score: str | None = None
    severities = vuln.get("severity", [])
    if isinstance(severities, list) and severities:
        for s in severities:
            if isinstance(s, dict):
                score_str = s.get("score", "")
                if score_str:
                    cvss_score = score_str
                    break

    if raw_sev == "CRITICAL":
        return VulnerabilitySeverity.CRITICAL, cvss_score
    elif raw_sev == "HIGH":
        return VulnerabilitySeverity.HIGH, cvss_score
    elif raw_sev in ("MODERATE", "MEDIUM"):
        return VulnerabilitySeverity.MEDIUM, cvss_score
    elif raw_sev == "LOW":
        return VulnerabilitySeverity.LOW, cvss_score

    # Fallback to CVSS score calculation if available
    if cvss_score:
        match = re.search(r"/S:[U|C]/C:[N|L|H]/I:[N|L|H]/A:[N|L|H]", cvss_score)
        if match:
            # Simple heuristic
            if "C:H" in cvss_score and "I:H" in cvss_score and "A:H" in cvss_score:
                return VulnerabilitySeverity.CRITICAL, cvss_score
            elif "C:H" in cvss_score or "I:H" in cvss_score or "A:H" in cvss_score:
                return VulnerabilitySeverity.HIGH, cvss_score

    return VulnerabilitySeverity.HIGH if raw_sev else VulnerabilitySeverity.UNKNOWN, cvss_score


def _find_cve_alias(aliases: list[str]) -> str | None:
    """Find primary CVE identifier from advisory aliases."""
    for alias in aliases:
        if isinstance(alias, str) and alias.upper().startswith("CVE-"):
            return alias.upper()
    return None


def scan_vulnerabilities(
    manifests: list[ProjectManifest],
    offline: bool = False,
    osv_client: OSVClient | None = None,
) -> SecurityReport:
    """
    Batch query OSV.dev for known vulnerabilities across all project dependencies.
    """
    client = osv_client or OSVClient()

    query_meta: list[tuple[ProjectManifest, str, str, Ecosystem]] = []
    queries: list[dict[str, Any]] = []

    seen_project_deps: set[tuple[str, str, str]] = set()

    for manifest in manifests:
        ecosystem_name = (
            "npm" if manifest.ecosystem == Ecosystem.NODE
            else "PyPI" if manifest.ecosystem == Ecosystem.PYTHON
            else "crates.io" if manifest.ecosystem == Ecosystem.RUST
            else "Go" if manifest.ecosystem == Ecosystem.GO
            else None
        )
        if not ecosystem_name:
            continue

        for dep in manifest.dependencies:
            # Skip internal workspace packages
            if dep.metadata.get("workspace_internal"):
                continue

            version = dep.resolved_version or dep.version_spec
            if not version or version in ("*", "latest"):
                continue

            # Strip prefixes like ^, ~, v
            clean_ver = re.sub(r"^[v=~^><\s]+", "", version).strip()
            if not clean_ver or clean_ver.startswith(("git+", "http:", "https:", "file:")):
                continue

            dedup_key = (str(manifest.project_path), dep.name.lower(), clean_ver)
            if dedup_key in seen_project_deps:
                continue
            seen_project_deps.add(dedup_key)

            query_meta.append((manifest, dep.name, clean_ver, manifest.ecosystem))
            queries.append({
                "package": {
                    "name": dep.name,
                    "ecosystem": ecosystem_name,
                },
                "version": clean_ver,
            })

    if not queries:
        return SecurityReport(advisories=[], scanned_packages=0)

    batch_results = client.query_batch(queries, offline=offline)
    advisories: list[VulnerabilityAdvisory] = []

    for (manifest, pkg_name, ver, eco), vulns_list in zip(query_meta, batch_results, strict=False):
        for vuln in vulns_list:
            if not isinstance(vuln, dict):
                continue

            vuln_id = vuln.get("id", "UNKNOWN-ADVISORY")
            aliases = vuln.get("aliases", [])
            cve_id = _find_cve_alias(aliases) if isinstance(aliases, list) else None
            summary = vuln.get("summary") or vuln.get("details", "")[:100] or "Security vulnerability detected"
            details = vuln.get("details", "")
            severity, cvss = _parse_severity(vuln)

            advisories.append(
                VulnerabilityAdvisory(
                    id=vuln_id,
                    cve_id=cve_id,
                    package_name=pkg_name,
                    installed_version=ver,
                    ecosystem=eco,
                    summary=summary.strip(),
                    details=details.strip(),
                    severity=severity,
                    cvss_score=cvss,
                    project_path=manifest.project_path,
                    project_name=manifest.project_name or manifest.project_path.name,
                )
            )

    return SecurityReport(
        advisories=advisories,
        scanned_packages=len(queries),
    )
