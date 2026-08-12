from __future__ import annotations

from typing import List, Dict
from datetime import datetime

from zerogravity.parsers.base import ProjectManifest
from zerogravity.resolver.models import (
    Severity, IssueCategory, Issue, ResolutionReport, SystemSnapshot
)
from zerogravity.resolver.comparator import compare_version
from zerogravity.resolver.binary_lookup import lookup_system_deps

def _check_engine_constraints(manifest: ProjectManifest, snapshot: SystemSnapshot) -> List[Issue]:
    issues = []
    if not manifest.engine_constraints:
        return issues
        
    for engine, spec in manifest.engine_constraints.items():
        binary = snapshot.get_binary(engine)
        if not binary or not binary.installed:
            issues.append(Issue(
                severity=Severity.CRITICAL,
                category=IssueCategory.MISSING_BINARY,
                message=f"Required engine '{engine}' is not installed.",
                source_project=manifest.project_path,
                affected_binary=engine,
                expected=spec,
                actual=None,
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
                source_project=manifest.project_path,
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
                source_project=manifest.project_path,
                affected_binary=engine,
                expected=spec,
                actual=binary.version,
                remediation=f"Verify compatibility with {engine} {binary.version}.",
                metadata={}
            ))
            
    return issues

def _check_missing_system_deps(manifest: ProjectManifest, snapshot: SystemSnapshot) -> List[Issue]:
    issues = []
    required_deps = lookup_system_deps(manifest.dependencies)
    
    for req in required_deps:
        binary = snapshot.get_binary(req.required_binary)
        if not binary or not binary.installed:
            issues.append(Issue(
                severity=Severity.WARNING,
                category=IssueCategory.MISSING_SYSTEM_DEP,
                message=f"Package '{req.package_name}' requires system binary '{req.required_binary}' which is missing.",
                source_project=manifest.project_path,
                affected_binary=req.required_binary,
                expected="installed",
                actual="missing",
                remediation=f"Install {req.required_binary} using your system package manager.",
                metadata={}
            ))
            
    return issues

def _check_cross_project_conflicts(manifests: List[ProjectManifest], snapshot: SystemSnapshot) -> List[Issue]:
    issues = []
    engine_reqs: Dict[str, List[tuple[ProjectManifest, str]]] = {}
    
    for manifest in manifests:
        if not manifest.engine_constraints:
            continue
        for engine, spec in manifest.engine_constraints.items():
            if engine not in engine_reqs:
                engine_reqs[engine] = []
            engine_reqs[engine].append((manifest, spec))
            
    for engine, reqs in engine_reqs.items():
        if len(reqs) > 1:
            specs = [req[1] for req in reqs]
            if len(set(specs)) > 1:
                # Specs differ across projects
                msg_parts = [f"{req[0].project_name} needs {engine.capitalize()} {req[1]}" for req in reqs]
                msg = f"{' but '.join(msg_parts)}. Running both simultaneously may cause conflicts."
                
                issues.append(Issue(
                    severity=Severity.WARNING,
                    category=IssueCategory.CROSS_PROJECT_CONFLICT,
                    message=msg,
                    source_project=reqs[0][0].project_path,
                    affected_binary=engine,
                    expected=None,
                    actual=None,
                    remediation="Use version managers or isolated environments for each project.",
                    metadata={}
                ))
                
    return issues

def _check_lockfiles(manifest: ProjectManifest) -> List[Issue]:
    issues = []
    if not manifest.lockfile_present:
        issues.append(Issue(
            severity=Severity.INFO,
            category=IssueCategory.LOCKFILE_MISSING,
            message="No lockfile found. Dependency versions may drift between installs.",
            source_project=manifest.project_path,
            affected_binary=None,
            expected="present",
            actual="missing",
            remediation="Generate a lockfile for reproducible builds.",
            metadata={}
        ))
    return issues

def detect_conflicts(manifests: List[ProjectManifest], snapshot: SystemSnapshot, include_history: bool = True) -> ResolutionReport:
    """
    Main entry point. Runs all detection rules and aggregates into a single ResolutionReport.
    """
    from zerogravity.resolver.history import ScanHistoryManager
    
    issues = []
    
    # Cross-project checks
    all_manifests = list(manifests)
    if include_history:
        history_mgr = ScanHistoryManager()
        hist_manifests = history_mgr.load_recent_manifests()
        current_paths = {m.project_path for m in manifests}
        for hm in hist_manifests:
            if hm.project_path not in current_paths:
                all_manifests.append(hm)

    issues.extend(_check_cross_project_conflicts(all_manifests, snapshot))
    
    for manifest in manifests:
        issues.extend(_check_engine_constraints(manifest, snapshot))
        issues.extend(_check_missing_system_deps(manifest, snapshot))
        issues.extend(_check_lockfiles(manifest))
        
    if include_history:
        ScanHistoryManager().save_manifests(manifests)
        
    return ResolutionReport(
        issues=issues,
        scanned_projects=len(manifests),
        scanned_binaries=len(snapshot.binaries),
        timestamp=datetime.now()
    )
