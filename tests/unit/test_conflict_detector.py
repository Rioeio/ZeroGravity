from __future__ import annotations

from pathlib import Path

from zerogravity.parsers.base import (
    Dependency,
    DependencyType,
    Ecosystem,
    ProjectManifest,
)
from zerogravity.resolver.conflict_detector import detect_conflicts
from zerogravity.resolver.models import (
    IssueCategory,
    Severity,
    SystemSnapshot,
)


def test_no_conflicts_healthy_system(mock_system_snapshot: SystemSnapshot):
    """All engine constraints met — no errors or critical issues."""
    manifest = ProjectManifest(
        project_path=Path("/tmp/proj"),
        project_name="proj",
        ecosystem=Ecosystem.NODE,
        dependencies=[],
        engine_constraints={"node": ">=18.0.0"},
        lockfile_present=True,
        lockfile_path=Path("/tmp/proj/package-lock.json"),
        manifest_files=[Path("/tmp/proj/package.json")],
        metadata={}
    )
    report = detect_conflicts([manifest], mock_system_snapshot)
    assert not any(
        i.severity in (Severity.ERROR, Severity.CRITICAL) for i in report.issues
    )


def test_missing_binary_critical(mock_system_snapshot: SystemSnapshot):
    """Project needs ruby but it's not installed — should be CRITICAL."""
    manifest = ProjectManifest(
        project_path=Path("/tmp/proj"),
        project_name="proj",
        ecosystem=Ecosystem.RUBY,
        dependencies=[],
        engine_constraints={"ruby": ">=3.0.0"},
        lockfile_present=True,
        lockfile_path=Path("/tmp/proj/Gemfile.lock"),
        manifest_files=[Path("/tmp/proj/Gemfile")],
        metadata={}
    )
    report = detect_conflicts([manifest], mock_system_snapshot)
    critical_issues = [i for i in report.issues if i.severity == Severity.CRITICAL]
    assert len(critical_issues) > 0
    assert critical_issues[0].category == IssueCategory.MISSING_BINARY


def test_version_mismatch_error(mock_system_snapshot: SystemSnapshot):
    """Project needs node>=22 but system has 20.11.0 — should be ERROR."""
    manifest = ProjectManifest(
        project_path=Path("/tmp/proj"),
        project_name="proj",
        ecosystem=Ecosystem.NODE,
        dependencies=[],
        engine_constraints={"node": ">=22.0.0"},
        lockfile_present=True,
        lockfile_path=Path("/tmp/proj/package-lock.json"),
        manifest_files=[Path("/tmp/proj/package.json")],
        metadata={}
    )
    report = detect_conflicts([manifest], mock_system_snapshot)
    error_issues = [i for i in report.issues if i.severity == Severity.ERROR]
    assert len(error_issues) > 0
    assert error_issues[0].category == IssueCategory.ENGINE_CONSTRAINT_VIOLATION


def test_version_satisfied_ok(mock_system_snapshot: SystemSnapshot):
    """Project needs node>=18, system has 20.11.0 — should be OK."""
    manifest = ProjectManifest(
        project_path=Path("/tmp/proj"),
        project_name="proj",
        ecosystem=Ecosystem.NODE,
        dependencies=[],
        engine_constraints={"node": ">=18.0.0"},
        lockfile_present=True,
        lockfile_path=Path("/tmp/proj/package-lock.json"),
        manifest_files=[Path("/tmp/proj/package.json")],
        metadata={}
    )
    report = detect_conflicts([manifest], mock_system_snapshot)
    error_issues = [
        i for i in report.issues
        if i.severity in (Severity.ERROR, Severity.CRITICAL)
    ]
    assert len(error_issues) == 0


def test_cross_project_conflict(mock_system_snapshot: SystemSnapshot):
    """Two projects with different python version constraints — should warn."""
    manifest1 = ProjectManifest(
        project_path=Path("/tmp/proj1"),
        project_name="proj1",
        ecosystem=Ecosystem.PYTHON,
        dependencies=[],
        engine_constraints={"python": ">=3.10"},
        lockfile_present=True,
    )
    manifest2 = ProjectManifest(
        project_path=Path("/tmp/proj2"),
        project_name="proj2",
        ecosystem=Ecosystem.PYTHON,
        dependencies=[],
        engine_constraints={"python": "<3.9"},
        lockfile_present=True,
    )
    report = detect_conflicts([manifest1, manifest2], mock_system_snapshot)
    conflict_issues = [
        i for i in report.issues
        if i.category == IssueCategory.CROSS_PROJECT_CONFLICT
    ]
    assert len(conflict_issues) > 0


def test_missing_lockfile_info(mock_system_snapshot: SystemSnapshot):
    """Manifest without lockfile — should produce INFO issue."""
    manifest = ProjectManifest(
        project_path=Path("/tmp/proj"),
        project_name="proj",
        ecosystem=Ecosystem.NODE,
        dependencies=[],
        engine_constraints={"node": ">=18.0.0"},
        lockfile_present=False,
        lockfile_path=None,
    )
    report = detect_conflicts([manifest], mock_system_snapshot)
    info_issues = [
        i for i in report.issues
        if i.category == IssueCategory.LOCKFILE_MISSING
    ]
    assert len(info_issues) > 0
    assert info_issues[0].severity == Severity.INFO


def test_missing_system_dep(mock_system_snapshot: SystemSnapshot):
    """Project has cryptography but no openssl installed — should warn."""
    dep = Dependency(
        name="cryptography",
        version_spec=">=41.0.0",
        resolved_version="41.0.0",
        dep_type=DependencyType.PRODUCTION,
        source="requirements.txt",
    )
    manifest = ProjectManifest(
        project_path=Path("/tmp/proj"),
        project_name="proj",
        ecosystem=Ecosystem.PYTHON,
        dependencies=[dep],
        engine_constraints={},
        lockfile_present=True,
    )
    report = detect_conflicts([manifest], mock_system_snapshot)
    warn_issues = [
        i for i in report.issues
        if i.category == IssueCategory.MISSING_SYSTEM_DEP
    ]
    assert len(warn_issues) > 0
