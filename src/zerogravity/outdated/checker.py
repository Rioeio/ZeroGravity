"""
Outdated dependency checker comparing resolved versions against registry metadata.
"""

from __future__ import annotations

import fnmatch
import os
import re
import urllib.parse
from concurrent.futures import ThreadPoolExecutor

from packaging.version import InvalidVersion, Version

from zerogravity.outdated.models import OutdatedPackage, OutdatedReport, UpdateType
from zerogravity.outdated.registry_client import RegistryClient
from zerogravity.parsers.base import Dependency, Ecosystem, ProjectManifest


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


def is_private_dependency(dep: Dependency, manifest: ProjectManifest) -> bool:
    """Return True if dependency belongs to a private/internal registry."""
    if dep.metadata.get("workspace_internal"):
        return True

    eco = manifest.ecosystem
    if eco == Ecosystem.NODE:
        resolved = str(dep.metadata.get("resolved") or dep.metadata.get("source") or "")
        if resolved:
            try:
                parsed = urllib.parse.urlparse(resolved)
                if parsed.scheme in ("http", "https"):
                    host = parsed.netloc.lower()
                    if host not in ("registry.npmjs.org", "registry.yarnpkg.com"):
                        return True
            except (ValueError, TypeError):
                pass
        npmrc = manifest.project_path / ".npmrc"
        if npmrc.is_file() and dep.name.startswith("@"):
            scope = dep.name.split("/")[0]
            try:
                content = npmrc.read_text(encoding="utf-8")
                for line in content.splitlines():
                    clean_line = line.strip()
                    if clean_line.startswith(f"{scope}:registry") or clean_line.startswith(f"@{scope}:registry"):
                        val = clean_line.split("=", 1)[-1].strip()
                        if "registry.npmjs.org" not in val and "registry.yarnpkg.com" not in val:
                            return True
            except OSError:
                pass

    elif eco == Ecosystem.PYTHON:
        source = dep.metadata.get("source")
        if source:
            if isinstance(source, dict):
                src_type = source.get("type", "")
                registry = source.get("registry", "")
                if src_type in ("git", "path", "directory", "editable"):
                    return True
                if registry and "pypi.org" not in registry:
                    return True
            elif isinstance(source, str):
                s_lower = source.lower()
                if s_lower != "pypi" and not ("pypi.org" in s_lower or "pythonhosted.org" in s_lower):
                    return True

    elif eco == Ecosystem.RUST:
        source = dep.metadata.get("source")
        if source:
            s_str = str(source).lower()
            if not ("crates.io-index" in s_str or "index.crates.io" in s_str):
                return True

    elif eco == Ecosystem.GO:
        goprivate = os.environ.get("GOPRIVATE", "") or os.environ.get("GONOPROXY", "")
        if goprivate:
            for pattern in goprivate.split(","):
                pattern = pattern.strip()
                if pattern and fnmatch.fnmatch(dep.name, pattern):
                    return True
        if ".internal" in dep.name or dep.name.startswith("internal/"):
            return True

    return False


def check_outdated_dependencies(
    manifests: list[ProjectManifest],
    offline: bool = False,
    registry_client: RegistryClient | None = None,
    include_transitive: bool = False,
    max_workers: int = 8,
) -> OutdatedReport:
    """
    Scan resolved direct dependencies concurrently and check for registry updates.
    """
    client = registry_client or RegistryClient()
    outdated_pkgs: list[OutdatedPackage] = []
    unresolved: list[str] = []
    private_skipped: list[str] = []

    seen_project_deps: set[tuple[str, str]] = set()
    items_to_query: list[tuple[ProjectManifest, Dependency, str]] = []

    for manifest in manifests:
        for dep in manifest.dependencies:
            if dep.metadata.get("workspace_internal"):
                continue

            if not include_transitive and dep.metadata.get("transitive"):
                continue

            if is_private_dependency(dep, manifest):
                private_skipped.append(dep.name)
                continue

            if not dep.resolved_version:
                unresolved.append(dep.name)
                continue

            version_to_check = dep.resolved_version
            if version_to_check in ("*", "latest"):
                continue

            if version_to_check.startswith(("git+", "http:", "https:", "file:")):
                continue

            dedup_key = (str(manifest.project_path), dep.name.lower())
            if dedup_key in seen_project_deps:
                continue
            seen_project_deps.add(dedup_key)

            items_to_query.append((manifest, dep, version_to_check))

    def _query_item(item: tuple[ProjectManifest, Dependency, str]) -> tuple[tuple[ProjectManifest, Dependency, str], str | None]:
        man, d, _ = item
        latest: str | None = None
        if man.ecosystem == Ecosystem.NODE:
            latest = client.get_latest_npm_version(d.name, offline=offline)
        elif man.ecosystem == Ecosystem.PYTHON:
            latest = client.get_latest_pypi_version(d.name, offline=offline)
        elif man.ecosystem == Ecosystem.RUST:
            latest = client.get_latest_crates_version(d.name, offline=offline)
        elif man.ecosystem == Ecosystem.GO:
            latest = client.get_latest_go_version(d.name, offline=offline)
        return (item, latest)

    workers = max(1, min(max_workers, len(items_to_query))) if items_to_query else 1
    with ThreadPoolExecutor(max_workers=workers) as executor:
        results = list(executor.map(_query_item, items_to_query))

    for (man, dep, version_to_check), latest_version in results:
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
                    ecosystem=man.ecosystem,
                    project_path=man.project_path,
                    project_name=man.project_name or man.project_path.name,
                    source=dep.source,
                )
            )

    return OutdatedReport(
        packages=outdated_pkgs,
        scanned_dependencies=len(items_to_query),
        errors=list(client.errors),
        complete=client.complete,
        unresolved=unresolved,
        private_skipped=private_skipped,
    )
