"""
Security scanner integrating OSV.dev batch query and vulnerability advisory extraction.
"""

from __future__ import annotations

import math
import re
from typing import Any

from zerogravity.outdated.checker import is_private_dependency
from zerogravity.parsers.base import Ecosystem, ProjectManifest
from zerogravity.security.models import (
    SecurityReport,
    VulnerabilityAdvisory,
    VulnerabilitySeverity,
)
from zerogravity.security.osv_client import OSVClient


def _cvss_roundup(val: float) -> float:
    """Official CVSS v3.1 roundup function."""
    int_input = round(val * 100000)
    if int_input % 10000 == 0:
        return int_input / 100000.0
    return (math.floor(int_input / 10000) + 1) / 10.0


def _compute_cvss_v3_score(vector: str) -> float | None:
    """Compute CVSS v3.x base score using the official CVSS v3.1 specification formula."""
    parts = dict(part.split(":", 1) for part in vector.split("/") if ":" in part)
    cvss_ver = parts.get("CVSS", "")
    if not (cvss_ver.startswith("3.0") or cvss_ver.startswith("3.1")):
        return None

    av_map = {"N": 0.85, "A": 0.62, "L": 0.55, "P": 0.20}
    ac_map = {"L": 0.77, "H": 0.44}
    ui_map = {"N": 0.85, "R": 0.62}
    c_map = {"H": 0.56, "L": 0.22, "N": 0.0}
    i_map = {"H": 0.56, "L": 0.22, "N": 0.0}
    a_map = {"H": 0.56, "L": 0.22, "N": 0.0}

    scope = parts.get("S")
    if scope not in ("U", "C"):
        return None

    pr_code = parts.get("PR")
    if scope == "U":
        pr_map = {"N": 0.85, "L": 0.62, "H": 0.27}
    else:
        pr_map = {"N": 0.85, "L": 0.68, "H": 0.50}

    try:
        av = av_map[parts["AV"]]
        ac = ac_map[parts["AC"]]
        pr = pr_map[pr_code]  # type: ignore[index]
        ui = ui_map[parts["UI"]]
        c = c_map[parts["C"]]
        i = i_map[parts["I"]]
        a = a_map[parts["A"]]
    except KeyError:
        return None

    iss = 1.0 - ((1.0 - c) * (1.0 - i) * (1.0 - a))
    if scope == "U":
        impact = 6.42 * iss
    else:
        impact = 7.52 * (iss - 0.029) - 3.25 * ((iss - 0.02) ** 15)

    exploitability = 8.22 * av * ac * pr * ui

    if impact <= 0:
        return 0.0
    if scope == "U":
        return _cvss_roundup(min(impact + exploitability, 10.0))
    return _cvss_roundup(min(1.08 * (impact + exploitability), 10.0))


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
        if cvss_score.startswith("CVSS:4.0") or "/VC:" in cvss_score:
            return VulnerabilitySeverity.UNKNOWN, cvss_score

        base_score = _compute_cvss_v3_score(cvss_score)
        if base_score is not None:
            if base_score >= 9.0:
                return VulnerabilitySeverity.CRITICAL, cvss_score
            elif base_score >= 7.0:
                return VulnerabilitySeverity.HIGH, cvss_score
            elif base_score >= 4.0:
                return VulnerabilitySeverity.MEDIUM, cvss_score
            elif base_score >= 0.1:
                return VulnerabilitySeverity.LOW, cvss_score

    return VulnerabilitySeverity.UNKNOWN, cvss_score


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
    no_cache: bool = False,
) -> SecurityReport:
    """
    Batch query OSV.dev for known vulnerabilities across resolved project dependencies.
    """
    client = osv_client or OSVClient()

    query_meta: list[tuple[ProjectManifest, str, str, Ecosystem]] = []
    queries: list[dict[str, Any]] = []

    seen_project_deps: set[tuple[str, str, str]] = set()
    unresolved_count = 0

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

            # Skip private dependencies
            if is_private_dependency(dep, manifest):
                continue

            # Query only resolved versions; range-only specs are counted as unresolved
            if not dep.resolved_version:
                unresolved_count += 1
                continue

            version = dep.resolved_version
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
        return SecurityReport(
            advisories=[],
            scanned_packages=0,
            unresolved_packages=unresolved_count,
            errors=list(client.errors),
            complete=client.complete,
        )

    batch_results = client.query_batch(queries, offline=offline, no_cache=no_cache)
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
        unresolved_packages=unresolved_count,
        errors=list(client.errors),
        complete=client.complete,
    )
