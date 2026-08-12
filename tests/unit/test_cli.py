from __future__ import annotations

import pytest
from typer.testing import CliRunner
from zerogravity.cli import app
from pathlib import Path

runner = CliRunner()


def test_cli_version():
    """Test --version flag."""
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert "ZeroGravity v0.2.0" in result.stdout


def test_cli_help():
    """Test main help output."""
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "Bridge the gap" in result.stdout


def test_audit_command():
    """Test zg audit command."""
    result = runner.invoke(app, ["audit"])
    assert result.exit_code == 0
    assert "System Binary Audit" in result.stdout


def test_audit_json_format():
    """Test zg audit --format json."""
    result = runner.invoke(app, ["audit", "--format", "json"])
    assert result.exit_code == 0
    assert '"binaries"' in result.stdout


def test_status_command():
    """Test zg status command."""
    result = runner.invoke(app, ["status"])
    assert result.exit_code == 0
    assert "System Health Dashboard" in result.stdout


def test_scan_node_fixture(node_project_path: Path):
    """Test zg scan on Node fixture."""
    result = runner.invoke(app, ["scan", str(node_project_path)])
    assert result.exit_code == 0
    assert "Project Manifests" in result.stdout


def test_scan_python_fixture(python_project_path: Path):
    """Test zg scan on Python fixture."""
    result = runner.invoke(app, ["scan", str(python_project_path)])
    assert result.exit_code == 0
    assert "Project Manifests" in result.stdout
    assert "Conflict Report" in result.stdout


def test_scan_json_format(node_project_path: Path):
    """Test zg scan --format json."""
    result = runner.invoke(app, ["scan", str(node_project_path), "--format", "json"])
    assert result.exit_code == 0
    assert '"manifests"' in result.stdout


def test_scan_multiple_paths(node_project_path: Path, python_project_path: Path):
    """Test zg scan with multiple directory paths."""
    result = runner.invoke(
        app, ["scan", str(node_project_path), str(python_project_path)]
    )
    assert result.exit_code == 0
    assert "test-node-app" in result.stdout
    assert "test-python-app" in result.stdout


def test_scan_recursive(tmp_path: Path):
    """Test zg scan --recursive."""
    sub = tmp_path / "subproject"
    sub.mkdir()
    (sub / "package.json").write_text('{"name": "sub-app"}')

    result = runner.invoke(app, ["scan", str(tmp_path), "--recursive"])
    assert result.exit_code == 0
    assert "sub-app" in result.stdout


def test_dedup_status():
    """Test zg dedup status command."""
    result = runner.invoke(app, ["dedup", "status"])
    assert result.exit_code == 0
    assert "Deduplication Status" in result.stdout


def test_dedup_scan(tmp_path: Path):
    """Test zg dedup scan command."""
    p1 = tmp_path / "p1"
    p1.mkdir()
    (p1 / "package.json").write_text('{"name": "p1"}')

    result = runner.invoke(app, ["dedup", "scan", str(p1)])
    assert result.exit_code == 0
    assert "Deduplication Report" in result.stdout


def test_dedup_optimize_dry_run(tmp_path: Path):
    """Test zg dedup optimize --dry-run command."""
    pkg = tmp_path / "node_modules" / "test-pkg"
    pkg.mkdir(parents=True)
    (pkg / "index.js").write_text("console.log('dry run');")

    result = runner.invoke(app, ["dedup", "optimize", str(pkg), "--dry-run"])
    assert result.exit_code == 0
    assert "DRY RUN" in result.stdout


def test_heal_command_dry_run(node_project_path: Path):
    """Test zg heal command."""
    result = runner.invoke(app, ["heal", str(node_project_path), "--auto-approve"])
    assert result.exit_code == 0
    assert "Conflict Report" in result.stdout
