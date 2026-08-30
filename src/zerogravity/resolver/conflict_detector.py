from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from zerogravity.parsers.base import ProjectManifest
from zerogravity.resolver.binary_lookup import lookup_system_deps
from zerogravity.resolver.comparator import compare_version
from zerogravity.resolver.models import (
    Issue,
    IssueCategory,
    ResolutionReport,
    Severity,
    SystemSnapshot,
)


def _check_engine_constraints(manifest: ProjectManifest, snapshot: SystemSnapshot) -> List[Issue]:
    issues: List[Issue] = []
    if not manifest.engine_constraints:
        return issues

    for engine, spec in manifest.engine_constraints.items():
        binary = snapshot.get_binary(engine)
        if not binary or not binary.installed:
            issues.append(Issue(
                severity=Severity.CRITICAL,
                category=IssueCategory.MISSING_BINARY,
                message=f"Required engine '{engine}' is not installed.",
                source_project=str(manifest.project_path),
                affected_binary=engine,
                expected=spec,
                actual="",
                remediation=f"Run: nvm install {spec}" if engine == "node" else f"Install {engine} matching {spec}",
                metadata={}
            ))
            continue

        if not binary.version:
            continue

        severity = compare_version(spec, binary.version)
        if severity == Severity.ERROR:
            issues.append(Issue(
                severity=Severity.ERROR,
                category=IssueCategory.ENGINE_CONSTRAINT_VIOLATION,
                message=f"Engine '{engine}' version {binary.version} does not satisfy constraint {spec}.",
                source_project=str(manifest.project_path),
                affected_binary=engine,
                expected=spec,
                actual=binary.version,
                remediation=f"Install {engine} matching {spec}.",
                metadata={}
            ))
        elif severity == Severity.WARNING:
            issues.append(Issue(
                severity=Severity.WARNING,
                category=IssueCategory.ENGINE_CONSTRAINT_VIOLATION,
                message=f"Engine '{engine}' version {binary.version} is newer than constraint {spec}.",
                source_project=str(manifest.project_path),
                affected_binary=engine,
                expected=spec,
                actual=binary.version,
                remediation=f"Verify compatibility with {engine} {binary.version}.",
                metadata={}
            ))

    return issues

def _check_missing_system_deps(
    manifest: ProjectManifest,
    snapshot: SystemSnapshot,
    custom_binary_map: dict[str, list[str]] | None = None,
    check_host_anyway: bool = False,
) -> List[Issue]:
    issues: List[Issue] = []

    # Container / devcontainer awareness
    if manifest.has_container and not check_host_anyway:
        container_name = manifest.container_file.name if manifest.container_file else "container configuration"
        issues.append(Issue(
            severity=Severity.INFO,
            category=IssueCategory.CONTAINER_RESOLVED,
            message=f"Project is configured with {container_name}. Host system-binary checks skipped (build-time dependencies are container-resolved).",
            source_project=str(manifest.project_path),
            affected_binary="",
            expected="container",
            actual="container",
            remediation="Use --check-host-anyway to force host system-binary probing.",
            metadata={"container_file": str(manifest.container_file) if manifest.container_file else ""}
        ))
        return issues

    required_deps = lookup_system_deps(manifest.dependencies, custom_map=custom_binary_map)

    for req in required_deps:
        binary = snapshot.get_binary(req.required_binary)
        if not binary or not binary.installed:
            issues.append(Issue(
                severity=Severity.WARNING,
                category=IssueCategory.MISSING_SYSTEM_DEP,
                message=f"Package '{req.package_name}' requires system binary '{req.required_binary}' which is missing.",
                source_project=str(manifest.project_path),
                affected_binary=req.required_binary,
                expected="installed",
                actual="missing",
                remediation=f"Install {req.required_binary} using your system package manager.",
                metadata={"package_name": req.package_name}
            ))

    return issues

def _check_cross_project_conflicts(manifests: List[ProjectManifest], snapshot: SystemSnapshot) -> List[Issue]:
    issues: List[Issue] = []
    engine_reqs_by_project: Dict[str, Dict[Path, List[tuple[ProjectManifest, str]]]] = {}

    for manifest in manifests:
        if not manifest.engine_constraints:
            continue
        proj_key = manifest.logical_project_path
        for engine, spec in manifest.engine_constraints.items():
            if engine not in engine_reqs_by_project:
                engine_reqs_by_project[engine] = {}
            if proj_key not in engine_reqs_by_project[engine]:
                engine_reqs_by_project[engine][proj_key] = []
            engine_reqs_by_project[engine][proj_key].append((manifest, spec))

    for engine, projects_dict in engine_reqs_by_project.items():
        # Sibling workspace packages belong to one logical project and do not conflict
        if len(projects_dict) > 1:
            project_specs = []
            all_distinct_specs = set()
            for proj_path, req_list in projects_dict.items():
                specs = list({r[1] for r in req_list})
                all_distinct_specs.update(specs)
                project_specs.append((req_list[0][0], specs))

            if len(all_distinct_specs) > 1:
                # Specs differ across distinct projects
                msg_parts = [
                    f"{m.project_name or m.project_path.name} needs {engine.capitalize()} {', '.join(specs)}"
                    for m, specs in project_specs
                ]
                msg = f"{' but '.join(msg_parts)}. Running both simultaneously may cause conflicts."

                issues.append(Issue(
                    severity=Severity.WARNING,
                    category=IssueCategory.CROSS_PROJECT_CONFLICT,
                    message=msg,
                    source_project=str(project_specs[0][0].project_path),
                    affected_binary=engine,
                    expected="",
                    actual="",
                    remediation="Use version managers or isolated environments for each project.",
                    metadata={}
                ))

    return issues

def _check_lockfiles(manifest: ProjectManifest) -> List[Issue]:
    issues: List[Issue] = []
    if not manifest.lockfile_present:
        issues.append(Issue(
            severity=Severity.INFO,
            category=IssueCategory.LOCKFILE_MISSING,
            message="No lockfile found. Dependency versions may drift between installs.",
            source_project=str(manifest.project_path),
            affected_binary="",
            expected="present",
            actual="missing",
            remediation="Generate a lockfile for reproducible builds.",
            metadata={}
        ))
    return issues

def detect_conflicts(
    manifests: List[ProjectManifest],
    snapshot: SystemSnapshot,
    include_history: bool = True,
    config: Any = None,
    check_host_anyway: bool = False,
) -> ResolutionReport:
    """
    Main entry point. Runs all detection rules and aggregates into a single ResolutionReport.
    Applies custom binary mappings and filters ignored issues/packages from configuration.
    """
    from zerogravity.config import ZeroGravityConfig, load_config
    from zerogravity.resolver.history import ScanHistoryManager

    if config is None:
        if manifests:
            config = load_config(manifests[0].logical_project_path)
        else:
            config = load_config()
    elif not isinstance(config, ZeroGravityConfig):
        config = ZeroGravityConfig()

    issues: List[Issue] = []

    # Cross-project checks
    all_manifests = list(manifests)
    if include_history:
        history_mgr = ScanHistoryManager()
        hist_manifests = history_mgr.load_recent_manifests()
        current_logical_paths = {m.logical_project_path for m in manifests}
        for hm in hist_manifests:
            if hm.logical_project_path not in current_logical_paths and hm.project_path not in {m.project_path for m in manifests}:
                all_manifests.append(hm)

    issues.extend(_check_cross_project_conflicts(all_manifests, snapshot))

    custom_bmap = config.binary_map if config else None

    for manifest in manifests:
        issues.extend(_check_engine_constraints(manifest, snapshot))
        issues.extend(_check_missing_system_deps(
            manifest,
            snapshot,
            custom_binary_map=custom_bmap,
            check_host_anyway=check_host_anyway,
        ))
        issues.extend(_check_lockfiles(manifest))

    # Filter ignored issues and packages
    if config and (config.ignore_issues or config.ignore_packages):
        filtered_issues = []
        for issue in issues:
            cat_name = issue.category.value.lower()
            if cat_name in config.ignore_issues or issue.category.name.lower() in config.ignore_issues:
                continue

            pkg_meta = issue.metadata.get("package_name", "").lower()
            aff_bin = issue.affected_binary.lower()
            if pkg_meta and pkg_meta in config.ignore_packages:
                continue
            if aff_bin and aff_bin in config.ignore_packages:
                continue

            filtered_issues.append(issue)
        issues = filtered_issues

    if include_history:
        ScanHistoryManager().save_manifests(manifests)

    return ResolutionReport(
        issues=issues,
        scanned_projects=len(manifests),
        scanned_binaries=len(snapshot.binaries),
        timestamp=datetime.now()
    )
