"""
Outdated dependency checker comparing resolved versions against registry metadata.
"""

from __future__ import annotations

import re

from packaging.version import InvalidVersion, Version

from zerogravity.outdated.models import OutdatedPackage, OutdatedReport, UpdateType
from zerogravity.outdated.registry_client import RegistryClient
from zerogravity.parsers.base import Ecosystem, ProjectManifest


def _clean_version_string(v_str: str) -> str:
    """Extract numeric version string from specifiers or prefixed tags."""
    v_str = v_str.strip().lstrip("v=").strip()
    match = re.search(r"(\d+(?:\.\d+)*(?:[a-zA-Z0-9_\-\.]+)*)", v_str)
    if match:
        return match.group(1)
    return v_str


def classify_update(current_str: str, latest_str: str) -> UpdateType:
    """
    Determine whether the update is a MAJOR, MINOR, or PATCH release.
    """
    clean_curr = _clean_version_string(current_str)
    clean_latest = _clean_version_string(latest_str)

    try:
        curr_ver = Version(clean_curr)
        latest_ver = Version(clean_latest)
    except InvalidVersion:
        # Fallback to simple split comparison if packaging cannot parse
        return _fallback_version_compare(clean_curr, clean_latest)

    if latest_ver <= curr_ver:
        return UpdateType.UP_TO_DATE

    if latest_ver.major > curr_ver.major:
        return UpdateType.MAJOR
    elif latest_ver.minor > curr_ver.minor:
        return UpdateType.MINOR
    elif latest_ver.micro > curr_ver.micro:
        return UpdateType.PATCH
    else:
        return UpdateType.PATCH


def _fallback_version_compare(current: str, latest: str) -> UpdateType:
    """Basic numeric fallback comparison."""
    c_parts = [int(p) for p in re.findall(r"\d+", current)]
    l_parts = [int(p) for p in re.findall(r"\d+", latest)]

    if not c_parts or not l_parts:
        return UpdateType.UNKNOWN

    while len(c_parts) < 3:
        c_parts.append(0)
    while len(l_parts) < 3:
        l_parts.append(0)

    if l_parts[0] > c_parts[0]:
        return UpdateType.MAJOR
    elif l_parts[1] > c_parts[1]:
        return UpdateType.MINOR
    elif l_parts[2] > c_parts[2]:
        return UpdateType.PATCH
    return UpdateType.UP_TO_DATE


def check_outdated_dependencies(
    manifests: list[ProjectManifest],
    offline: bool = False,
    registry_client: RegistryClient | None = None,
) -> OutdatedReport:
    """
    Scan all resolved dependencies in the provided manifests and check for updates.
    """
    client = registry_client or RegistryClient()
    outdated_pkgs: list[OutdatedPackage] = []
    scanned_count = 0

    seen_project_deps: set[tuple[str, str]] = set()

    for manifest in manifests:
        for dep in manifest.dependencies:
            # Skip workspace-internal dependencies
            if dep.metadata.get("workspace_internal"):
                continue

            # Need a concrete version to check
            version_to_check = dep.resolved_version or dep.version_spec
            if not version_to_check or version_to_check in ("*", "latest"):
                continue

            # Skip VCS / URL direct dependencies without semantic version
            if version_to_check.startswith(("git+", "http:", "https:", "file:")):
                continue

            dedup_key = (str(manifest.project_path), dep.name.lower())
            if dedup_key in seen_project_deps:
                continue
            seen_project_deps.add(dedup_key)

            scanned_count += 1
            latest_version: str | None = None

            if manifest.ecosystem == Ecosystem.NODE:
                latest_version = client.get_latest_npm_version(dep.name, offline=offline)
            elif manifest.ecosystem == Ecosystem.PYTHON:
                latest_version = client.get_latest_pypi_version(dep.name, offline=offline)

            if not latest_version:
                continue

            update_type = classify_update(version_to_check, latest_version)
            if update_type in (UpdateType.MAJOR, UpdateType.MINOR, UpdateType.PATCH):
                outdated_pkgs.append(
                    OutdatedPackage(
                        name=dep.name,
                        current_version=version_to_check,
                        latest_version=latest_version,
                        update_type=update_type,
                        ecosystem=manifest.ecosystem,
                        project_path=manifest.project_path,
                        project_name=manifest.project_name or manifest.project_path.name,
                        source=dep.source,
                    )
                )

    return OutdatedReport(
        packages=outdated_pkgs,
        scanned_dependencies=scanned_count,
    )
