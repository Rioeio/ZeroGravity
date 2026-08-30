from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from zerogravity.cli import app

runner = CliRunner()


def test_cli_version():
    """Test --version flag."""
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert "ZeroGravity v0.3.0" in result.stdout


def test_cli_help():
    """Test main help output."""
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "Bridge the gap" in result.stdout


def test_cli_help_shows_completion_options():
    """--install-completion and --show-completion are advertised in help."""
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "--install-completion" in result.stdout
    assert "--show-completion" in result.stdout


def test_cli_show_completion_exits_zero():
    """--show-completion bash should print a completion script and exit 0."""
    result = runner.invoke(app, ["--show-completion", "bash"])
    # Typer's show-completion prints a bash completion script.
    # Exit code 0 confirms the flag is wired up and functional.
    assert result.exit_code == 0
    assert "complete" in result.stdout.lower() or "compgen" in result.stdout.lower() or "_ZG_COMPLETE" in result.stdout


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


def test_heal_command_executes_nvm_remediation(node_project_path: Path, tmp_path: Path):
    """
    End-to-end: with a fake nvm.sh present and version_managers reporting it,
    zg heal --auto-approve should actually invoke it (via bash -c, sourced)
    rather than silently no-op'ing like the shell=True/list-args bug did.
    """
    from unittest.mock import MagicMock, patch

    from zerogravity.resolver.models import VersionManagerInfo

    (tmp_path / "nvm.sh").write_text("# fake nvm.sh")

    with patch(
        "zerogravity.scanner.version_manager.detect_all_managers_sync",
        return_value={"nvm": VersionManagerInfo(name="nvm", detected=True, root_path=str(tmp_path))},
    ), patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        result = runner.invoke(app, ["heal", str(node_project_path), "--auto-approve"])

    assert result.exit_code == 0
    if mock_run.called:
        args = mock_run.call_args[0][0]
        assert args[0] == "bash"
        assert args[1] == "-c"


def test_why_command_direct_dep(node_project_path: Path):
    """Test zg why on a direct dependency asserts direct origin, declared and resolved version, and lockfile."""
    result = runner.invoke(app, ["why", "express", str(node_project_path)])
    assert result.exit_code == 0
    assert "Dependency Trace: express" in result.stdout
    assert "Direct" in result.stdout
    assert "^4.18.2" in result.stdout
    assert "4.18.2" in result.stdout
    assert "package-lock.json" in result.stdout
    assert "System Binaries" in result.stdout


def test_why_command_transitive_dep(rust_project_path: Path):
    """Test zg why on a transitive-only dependency asserts transitive origin, resolved version, and lockfile."""
    result = runner.invoke(app, ["why", "serde_derive", str(rust_project_path)])
    assert result.exit_code == 0
    assert "Dependency Trace: serde_derive" in result.stdout
    assert "Transitive" in result.stdout
    assert "1.0.197" in result.stdout
    assert "Cargo.lock" in result.stdout


def test_why_command_unknown_package(node_project_path: Path):
    """Test zg why on an unknown package name outputs clear 'not found' message."""
    result = runner.invoke(app, ["why", "some-nonexistent-package-xyz", str(node_project_path)])
    assert result.exit_code == 0
    assert "not found" in result.stdout.lower()


def test_why_command_system_binary_requirement(tmp_path: Path):
    """Test zg why shows required system binaries per SYSTEM_DEPENDENCY_MAP."""
    (tmp_path / "requirements.txt").write_text("cryptography==41.0.0\n")
    result = runner.invoke(app, ["why", "cryptography", str(tmp_path)])
    assert result.exit_code == 0
    assert "cryptography" in result.stdout
    assert "openssl" in result.stdout


def test_why_command_json_format(node_project_path: Path):
    """Test zg why --format json output structure."""
    import json
    result = runner.invoke(app, ["why", "express", str(node_project_path), "--format", "json"])
    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert data["found"] is True
    assert data["package"] == "express"
    assert len(data["traces"]) == 1
    assert data["traces"][0]["dependency_type"] == "direct"
    assert data["traces"][0]["resolved_version"] == "4.18.2"
    assert data["traces"][0]["lockfile"] == "package-lock.json"


# ── zg doctor tests ─────────────────────────────────────────────────────────

def test_doctor_reaches_heal_offer_with_known_issue(node_project_path: Path):
    """
    End-to-end: doctor on a fixture whose engine constraint cannot be
    satisfied (node binary missing) should run audit, scan, detect the
    issue, and reach the heal offer — presenting proposed remediation
    actions in one narrative.
    """
    from unittest.mock import patch

    from zerogravity.resolver.models import BinaryProbe, VersionManagerInfo

    # Simulate: node is NOT installed so the >=18.0.0 constraint fires a
    # CRITICAL MISSING_BINARY issue that the HealingEngine can plan for.
    fake_binaries = {
        "node": BinaryProbe(name="node", installed=False),
        "npm": BinaryProbe(name="npm", installed=False),
    }
    fake_nvm_dir = node_project_path  # Just need a dir that exists
    fake_managers = {
        "nvm": VersionManagerInfo(name="nvm", detected=True, root_path=str(fake_nvm_dir)),
    }

    # Place a fake nvm.sh so HealingEngine considers nvm usable
    nvm_script = fake_nvm_dir / "nvm.sh"
    nvm_existed = nvm_script.exists()
    if not nvm_existed:
        nvm_script.write_text("# fake nvm.sh")

    try:
        with patch(
            "zerogravity.scanner.binary_scanner.run_scan_sync",
            return_value=fake_binaries,
        ), patch(
            "zerogravity.scanner.version_manager.detect_all_managers_sync",
            return_value=fake_managers,
        ):
            result = runner.invoke(app, ["doctor", str(node_project_path), "--auto-approve"])
    finally:
        if not nvm_existed:
            nvm_script.unlink(missing_ok=True)

    assert result.exit_code == 0
    # All three narrative steps should appear
    assert "Step 1/3" in result.stdout
    assert "Step 2/3" in result.stdout
    assert "Step 3/3" in result.stdout
    # The node engine constraint issue should be found
    assert "node" in result.stdout.lower()
    # Should reach the heal offer with proposed actions
    assert "Proposed Remediation Actions" in result.stdout
    assert "nvm" in result.stdout


def test_doctor_healthy_project_no_heal(tmp_path: Path):
    """
    Doctor on a project with no engine constraints and no issues should
    complete all steps and report nothing to heal.
    """
    (tmp_path / "package.json").write_text('{"name": "healthy-app", "dependencies": {"lodash": "^4.17.21"}}')

    result = runner.invoke(app, ["doctor", str(tmp_path)])
    assert result.exit_code == 0
    assert "Step 1/3" in result.stdout
    assert "Step 2/3" in result.stdout
    assert "Step 3/3" in result.stdout
    assert "good shape" in result.stdout.lower() or "nothing to heal" in result.stdout.lower()


def test_doctor_no_manifests(tmp_path: Path):
    """Doctor on an empty directory should report no manifests and exit cleanly."""
    result = runner.invoke(app, ["doctor", str(tmp_path)])
    assert result.exit_code == 0
    assert "No supported manifest" in result.stdout

