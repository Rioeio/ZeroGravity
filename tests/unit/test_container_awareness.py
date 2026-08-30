from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from zerogravity.cli import app
from zerogravity.parsers.base import (
    Dependency,
    DependencyType,
    Ecosystem,
    ProjectManifest,
    detect_container_config,
)
from zerogravity.parsers.registry import detect_and_parse
from zerogravity.resolver.conflict_detector import detect_conflicts
from zerogravity.resolver.models import IssueCategory, Severity, SystemSnapshot

runner = CliRunner()


def test_detect_container_config(tmp_path: Path):
    """Verify container discovery for Dockerfile, devcontainer.json, and compose files."""
    assert detect_container_config(tmp_path) is None

    # Dockerfile
    df = tmp_path / "Dockerfile"
    df.write_text("FROM node:20")
    assert detect_container_config(tmp_path) == df

    df.unlink()

    # .devcontainer/devcontainer.json
    devcontainer_dir = tmp_path / ".devcontainer"
    devcontainer_dir.mkdir()
    dc = devcontainer_dir / "devcontainer.json"
    dc.write_text('{"name": "dev"}')
    assert detect_container_config(tmp_path) == dc


def test_host_probing_skipped_with_container(tmp_path: Path, mock_system_snapshot: SystemSnapshot):
    """When a Dockerfile is present, host system binary checks are skipped and noted as container-resolved."""
    df = tmp_path / "Dockerfile"
    df.write_text("FROM python:3.11")

    dep = Dependency(name="cryptography", version_spec="*", dep_type=DependencyType.PRODUCTION)
    manifest = ProjectManifest(
        project_path=tmp_path,
        project_name="container-app",
        ecosystem=Ecosystem.PYTHON,
        dependencies=[dep],
        container_file=df,
    )

    # Missing openssl in snapshot
    report = detect_conflicts([manifest], mock_system_snapshot, include_history=False)

    # Should NOT have missing_system_dep warning
    assert not any(i.category == IssueCategory.MISSING_SYSTEM_DEP for i in report.issues)

    # Should have container_resolved INFO issue
    container_issues = [i for i in report.issues if i.category == IssueCategory.CONTAINER_RESOLVED]
    assert len(container_issues) == 1
    assert container_issues[0].severity == Severity.INFO
    assert "container-resolved" in container_issues[0].message


def test_host_probing_runs_without_container(tmp_path: Path, mock_system_snapshot: SystemSnapshot):
    """When no container config is present, host system binary checks run normally."""
    dep = Dependency(name="cryptography", version_spec="*", dep_type=DependencyType.PRODUCTION)
    manifest = ProjectManifest(
        project_path=tmp_path,
        project_name="host-app",
        ecosystem=Ecosystem.PYTHON,
        dependencies=[dep],
        container_file=None,
    )

    report = detect_conflicts([manifest], mock_system_snapshot, include_history=False)
    assert any(i.category == IssueCategory.MISSING_SYSTEM_DEP for i in report.issues)


def test_check_host_anyway_override(tmp_path: Path, mock_system_snapshot: SystemSnapshot):
    """--check-host-anyway forces host system binary probing even for containerized projects."""
    df = tmp_path / "Dockerfile"
    df.write_text("FROM python:3.11")

    dep = Dependency(name="cryptography", version_spec="*", dep_type=DependencyType.PRODUCTION)
    manifest = ProjectManifest(
        project_path=tmp_path,
        project_name="container-app",
        ecosystem=Ecosystem.PYTHON,
        dependencies=[dep],
        container_file=df,
    )

    report = detect_conflicts([manifest], mock_system_snapshot, include_history=False, check_host_anyway=True)
    assert any(i.category == IssueCategory.MISSING_SYSTEM_DEP for i in report.issues)


def test_parser_registry_populates_container_file(tmp_path: Path):
    """Parser registry automatically sets container_file on parsed manifests."""
    (tmp_path / "package.json").write_text('{"name": "containerized-pkg"}')
    (tmp_path / "Dockerfile").write_text("FROM node:20")

    manifests = detect_and_parse(tmp_path, use_cache=False)
    assert len(manifests) == 1
    assert manifests[0].has_container is True
    assert manifests[0].container_file == tmp_path / "Dockerfile"


def test_cli_scan_container_awareness(tmp_path: Path):
    """CLI zg scan respects container presence and --check-host-anyway."""
    (tmp_path / "pyproject.toml").write_text("""
[project]
name = "docker-app"
version = "0.1.0"
dependencies = ["cryptography"]
""")
    (tmp_path / "Dockerfile").write_text("FROM python:3.11")

    # Standard scan: skips missing system dep warning, displays container note
    res_default = runner.invoke(app, ["scan", str(tmp_path), "--offline", "--no-history", "--no-cache"])
    assert res_default.exit_code == 0
    assert "container-resolved" in res_default.stdout or "Container" in res_default.stdout

    # With --check-host-anyway: probes host
    res_override = runner.invoke(app, ["scan", str(tmp_path), "--check-host-anyway", "--offline", "--no-history", "--no-cache"])
    assert res_override.exit_code == 0
    assert "openssl" in res_override.stdout or "MISSING_SYSTEM_DEP" in res_override.stdout
