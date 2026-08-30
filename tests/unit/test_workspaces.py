from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from zerogravity.cli import app
from zerogravity.dedup.engine import DeduplicationEngine
from zerogravity.parsers.node_parser import NodeParser
from zerogravity.parsers.python_parser import PythonParser
from zerogravity.resolver.conflict_detector import detect_conflicts
from zerogravity.resolver.models import IssueCategory, SystemSnapshot

runner = CliRunner()


def test_node_workspace_parsing(node_workspace_path: Path):
    """Test parsing Node workspace root and member packages."""
    parser = NodeParser()

    # Root manifest
    root_manifest = parser.parse(node_workspace_path)
    assert root_manifest.is_workspace_root is True
    assert root_manifest.workspace_root == node_workspace_path.resolve()
    assert len(root_manifest.workspace_members) == 2
    assert root_manifest.logical_project_path == node_workspace_path.resolve()

    # Member pkg-a
    pkg_a_path = node_workspace_path / "packages" / "pkg-a"
    pkg_a_manifest = parser.parse(pkg_a_path)
    assert pkg_a_manifest.is_workspace_member is True
    assert pkg_a_manifest.workspace_root == node_workspace_path.resolve()
    assert pkg_a_manifest.logical_project_path == node_workspace_path.resolve()

    # Check that internal dependency @monorepo/pkg-b is marked as workspace_internal
    deps = {d.name: d for d in pkg_a_manifest.dependencies}
    assert "@monorepo/pkg-b" in deps
    assert deps["@monorepo/pkg-b"].metadata.get("workspace_internal") is True


def test_pnpm_workspace_parsing(tmp_path: Path):
    """Test pnpm-workspace.yaml with inclusion and exclusion globs."""
    ws_root = tmp_path / "pnpm_ws"
    (ws_root / "packages" / "app-1").mkdir(parents=True)
    (ws_root / "packages" / "app-2").mkdir(parents=True)
    (ws_root / "packages" / "test-app").mkdir(parents=True)

    (ws_root / "package.json").write_text('{"name": "root"}')
    (ws_root / "packages" / "app-1" / "package.json").write_text('{"name": "app-1"}')
    (ws_root / "packages" / "app-2" / "package.json").write_text('{"name": "app-2"}')
    (ws_root / "packages" / "test-app" / "package.json").write_text('{"name": "test-app"}')

    (ws_root / "pnpm-workspace.yaml").write_text(
        "packages:\n"
        "  - 'packages/*'\n"
        "  - '!packages/test-*'\n"
    )

    parser = NodeParser()
    manifest = parser.parse(ws_root)
    assert manifest.is_workspace_root is True
    member_names = [p.name for p in manifest.workspace_members]
    assert "app-1" in member_names
    assert "app-2" in member_names
    assert "test-app" not in member_names


def test_python_workspace_parsing(python_workspace_path: Path):
    """Test parsing Python workspace root and member packages with path dependencies."""
    parser = PythonParser()

    # Root manifest
    root_manifest = parser.parse(python_workspace_path)
    assert root_manifest.is_workspace_root is True
    assert root_manifest.workspace_root == python_workspace_path.resolve()
    assert len(root_manifest.workspace_members) == 2
    assert root_manifest.logical_project_path == python_workspace_path.resolve()

    # Member pkg-a
    pkg_a_path = python_workspace_path / "packages" / "pkg-a"
    pkg_a_manifest = parser.parse(pkg_a_path)
    assert pkg_a_manifest.is_workspace_member is True
    assert pkg_a_manifest.workspace_root == python_workspace_path.resolve()
    assert pkg_a_manifest.logical_project_path == python_workspace_path.resolve()

    # Check that internal dependency pkg-b is marked as workspace_internal
    deps = {d.name: d for d in pkg_a_manifest.dependencies}
    assert "pkg-b" in deps
    assert deps["pkg-b"].metadata.get("workspace_internal") is True


def test_workspace_zero_cross_project_conflicts(
    node_workspace_path: Path,
    mock_system_snapshot: SystemSnapshot,
):
    """
    A workspace fixture with 2+ member packages sharing an engine constraint
    produces zero false cross-project conflicts.
    """
    parser = NodeParser()
    root_manifest = parser.parse(node_workspace_path)
    pkg_a_manifest = parser.parse(node_workspace_path / "packages" / "pkg-a")
    pkg_b_manifest = parser.parse(node_workspace_path / "packages" / "pkg-b")

    manifests = [root_manifest, pkg_a_manifest, pkg_b_manifest]
    report = detect_conflicts(manifests, mock_system_snapshot, include_history=False)

    cross_conflicts = [
        i for i in report.issues
        if i.category == IssueCategory.CROSS_PROJECT_CONFLICT
    ]
    assert len(cross_conflicts) == 0


def test_python_workspace_zero_cross_project_conflicts(
    python_workspace_path: Path,
    mock_system_snapshot: SystemSnapshot,
):
    """
    Python workspace with 2+ member packages sharing python engine constraints
    produces zero false cross-project conflicts.
    """
    parser = PythonParser()
    root_manifest = parser.parse(python_workspace_path)
    pkg_a_manifest = parser.parse(python_workspace_path / "packages" / "pkg-a")
    pkg_b_manifest = parser.parse(python_workspace_path / "packages" / "pkg-b")

    manifests = [root_manifest, pkg_a_manifest, pkg_b_manifest]
    report = detect_conflicts(manifests, mock_system_snapshot, include_history=False)

    cross_conflicts = [
        i for i in report.issues
        if i.category == IssueCategory.CROSS_PROJECT_CONFLICT
    ]
    assert len(cross_conflicts) == 0


def test_workspace_vs_independent_project_conflict(
    node_workspace_path: Path,
    mock_system_snapshot: SystemSnapshot,
    tmp_path: Path,
):
    """
    Cross-project conflicts ARE detected when comparing a workspace against an external project
    with conflicting engine requirements, but not between workspace members.
    """
    # External project requiring Node <16
    ext_dir = tmp_path / "legacy_app"
    ext_dir.mkdir()
    (ext_dir / "package.json").write_text(
        '{"name": "legacy-app", "engines": {"node": "<16.0.0"}}'
    )

    parser = NodeParser()
    root_manifest = parser.parse(node_workspace_path)
    pkg_a_manifest = parser.parse(node_workspace_path / "packages" / "pkg-a")
    pkg_b_manifest = parser.parse(node_workspace_path / "packages" / "pkg-b")
    ext_manifest = parser.parse(ext_dir)

    manifests = [root_manifest, pkg_a_manifest, pkg_b_manifest, ext_manifest]
    report = detect_conflicts(manifests, mock_system_snapshot, include_history=False)

    cross_conflicts = [
        i for i in report.issues
        if i.category == IssueCategory.CROSS_PROJECT_CONFLICT
    ]
    # Exactly one cross-project conflict (between node-monorepo and legacy-app)
    assert len(cross_conflicts) == 1
    assert "node-monorepo" in cross_conflicts[0].message
    assert "legacy-app" in cross_conflicts[0].message


def test_dedup_does_not_flag_workspace_internal_shared_deps(tmp_path: Path):
    """
    Dedup scan treats sibling workspace packages as belonging to one logical project
    and does not flag workspace-internal shared dependency copies as candidates.
    """
    ws_dir = tmp_path / "my_workspace"
    pkg_a_modules = ws_dir / "packages" / "pkg-a" / "node_modules"
    pkg_b_modules = ws_dir / "packages" / "pkg-b" / "node_modules"

    pkg_a_modules.mkdir(parents=True)
    pkg_b_modules.mkdir(parents=True)

    (ws_dir / "package.json").write_text(
        '{"name": "my-workspace", "workspaces": ["packages/*"]}'
    )
    (ws_dir / "packages" / "pkg-a" / "package.json").write_text(
        '{"name": "@my-ws/pkg-a"}'
    )
    (ws_dir / "packages" / "pkg-b" / "package.json").write_text(
        '{"name": "@my-ws/pkg-b"}'
    )

    # Identical node_modules content inside sibling workspace packages
    (pkg_a_modules / "shared-dep.js").write_text("module.exports = 'shared';")
    (pkg_b_modules / "shared-dep.js").write_text("module.exports = 'shared';")

    engine = DeduplicationEngine(
        store_path=tmp_path / "store",
        db_path=tmp_path / "registry.db",
    )

    # Scanning within the workspace fixture
    report = engine.scan_for_duplicates([ws_dir])
    # Should not flag sibling packages in the same workspace as duplicate candidates
    assert len(report.groups) == 0
    assert report.total_waste_bytes == 0


def test_dedup_flags_duplicates_across_distinct_workspaces(tmp_path: Path):
    """
    Dedup scan DOES flag duplicate candidate groups that span across separate logical workspaces.
    """
    ws1 = tmp_path / "workspace_one"
    ws2 = tmp_path / "workspace_two"

    (ws1 / "node_modules").mkdir(parents=True)
    (ws2 / "node_modules").mkdir(parents=True)

    (ws1 / "package.json").write_text('{"name": "ws1", "workspaces": ["packages/*"]}')
    (ws2 / "package.json").write_text('{"name": "ws2", "workspaces": ["packages/*"]}')

    (ws1 / "node_modules" / "lib.js").write_text("console.log('identical lib');")
    (ws2 / "node_modules" / "lib.js").write_text("console.log('identical lib');")

    engine = DeduplicationEngine(
        store_path=tmp_path / "store",
        db_path=tmp_path / "registry.db",
    )

    report = engine.scan_for_duplicates([ws1, ws2])
    assert len(report.groups) == 1
    assert report.total_waste_bytes > 0


def test_cli_scan_recursive_node_workspace(node_workspace_path: Path):
    """CLI test: zg scan --recursive on Node workspace has no false cross-project conflicts."""
    result = runner.invoke(app, ["scan", str(node_workspace_path), "--recursive", "--no-history"])
    assert result.exit_code == 0
    assert "CROSS_PROJECT_CONFLICT" not in result.stdout


def test_cli_scan_recursive_python_workspace(python_workspace_path: Path):
    """CLI test: zg scan --recursive on Python workspace has no false cross-project conflicts."""
    result = runner.invoke(app, ["scan", str(python_workspace_path), "--recursive", "--no-history"])
    assert result.exit_code == 0
    assert "CROSS_PROJECT_CONFLICT" not in result.stdout
