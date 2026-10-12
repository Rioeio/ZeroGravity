from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from zerogravity.cli import app
from zerogravity.parsers.base import Ecosystem, ProjectManifest
from zerogravity.resolver.conflict_detector import _check_cross_project_conflicts
from zerogravity.resolver.history import ScanHistoryManager
from zerogravity.resolver.models import BinaryProbe, IssueCategory, SystemSnapshot

runner = CliRunner()


def _make_snapshot(python_version: str = "3.11.5") -> SystemSnapshot:
    return SystemSnapshot(
        binaries={
            "python": BinaryProbe(
                name="python",
                installed=True,
                path="/usr/bin/python",
                version=python_version,
                error=None,
            ),
            "python3": BinaryProbe(
                name="python3",
                installed=True,
                path="/usr/bin/python3",
                version=python_version,
                error=None,
            ),
        }
    )


def test_compatible_ranges_no_conflict():
    """>=3.10 vs >=3.11 overlap and should produce no conflict issue."""
    m1 = ProjectManifest(
        project_path=Path("/tmp/proj1"),
        project_name="proj1",
        ecosystem=Ecosystem.PYTHON,
        dependencies=[],
        engine_constraints={"python": ">=3.11"},
        lockfile_present=True,
    )
    m2 = ProjectManifest(
        project_path=Path("/tmp/proj2"),
        project_name="proj2",
        ecosystem=Ecosystem.PYTHON,
        dependencies=[],
        engine_constraints={"python": ">=3.10"},
        lockfile_present=True,
    )
    snapshot = _make_snapshot("3.11.5")
    issues = _check_cross_project_conflicts([m1, m2], snapshot)
    conflict_issues = [i for i in issues if i.category == IssueCategory.CROSS_PROJECT_CONFLICT]
    assert len(conflict_issues) == 0


def test_incompatible_ranges_produce_conflict():
    """>=3.12 vs <3.10 have an empty intersection and produce one conflict issue naming both."""
    m1 = ProjectManifest(
        project_path=Path("/tmp/proj1"),
        project_name="proj1",
        ecosystem=Ecosystem.PYTHON,
        dependencies=[],
        engine_constraints={"python": ">=3.12"},
        lockfile_present=True,
    )
    m2 = ProjectManifest(
        project_path=Path("/tmp/proj2"),
        project_name="proj2",
        ecosystem=Ecosystem.PYTHON,
        dependencies=[],
        engine_constraints={"python": "<3.10"},
        lockfile_present=True,
    )
    snapshot = _make_snapshot("3.11.5")
    issues = _check_cross_project_conflicts([m1, m2], snapshot)
    conflict_issues = [i for i in issues if i.category == IssueCategory.CROSS_PROJECT_CONFLICT]
    assert len(conflict_issues) == 1
    msg = conflict_issues[0].message
    assert "proj1" in msg
    assert "proj2" in msg


def test_duplicate_project_entries_produce_one_clause():
    """Duplicate project entries should not repeat clauses in conflict messages."""
    m1 = ProjectManifest(
        project_path=Path("/tmp/proj1"),
        project_name="proj1",
        ecosystem=Ecosystem.PYTHON,
        dependencies=[],
        engine_constraints={"python": ">=3.12"},
        lockfile_present=True,
    )
    m2 = ProjectManifest(
        project_path=Path("/tmp/proj2"),
        project_name="proj2",
        ecosystem=Ecosystem.PYTHON,
        dependencies=[],
        engine_constraints={"python": "<3.10"},
        lockfile_present=True,
    )
    m2_dup = ProjectManifest(
        project_path=Path("/tmp/proj2"),
        project_name="proj2",
        ecosystem=Ecosystem.PYTHON,
        dependencies=[],
        engine_constraints={"python": "<3.10"},
        lockfile_present=True,
    )
    snapshot = _make_snapshot("3.11.5")
    issues = _check_cross_project_conflicts([m1, m2, m2_dup], snapshot)
    conflict_issues = [i for i in issues if i.category == IssueCategory.CROSS_PROJECT_CONFLICT]
    assert len(conflict_issues) == 1
    msg = conflict_issues[0].message
    assert msg.count("proj2") == 1


def test_cap_messages_at_three_projects():
    """Messages with >3 projects cap at 3 projects and append 'and N more'."""
    manifests = []
    specs = [">=3.12", ">=3.12", "<3.10", "<3.10", "<3.10"]
    for idx, spec in enumerate(specs):
        manifests.append(ProjectManifest(
            project_path=Path(f"/tmp/proj{idx}"),
            project_name=f"proj{idx}",
            ecosystem=Ecosystem.PYTHON,
            dependencies=[],
            engine_constraints={"python": spec},
            lockfile_present=True,
        ))
    snapshot = _make_snapshot("3.11.5")
    issues = _check_cross_project_conflicts(manifests, snapshot)
    conflict_issues = [i for i in issues if i.category == IssueCategory.CROSS_PROJECT_CONFLICT]
    assert len(conflict_issues) == 1
    msg = conflict_issues[0].message
    assert "and 2 more" in msg


def test_history_list_and_clear_commands(tmp_path: Path, monkeypatch):
    """zg history list and zg history clear manage local scan history."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))

    mgr = ScanHistoryManager()
    mgr.history_dir = tmp_path / ".zerogravity"
    mgr.history_file = mgr.history_dir / "scan_history.json"

    p1 = tmp_path / "p1"
    p1.mkdir()
    p2 = tmp_path / "p2"
    p2.mkdir()

    m1 = ProjectManifest(
        project_path=p1,
        project_name="app1",
        ecosystem=Ecosystem.PYTHON,
        dependencies=[],
        engine_constraints={"python": ">=3.11"},
        lockfile_present=True,
    )
    m2 = ProjectManifest(
        project_path=p2,
        project_name="app2",
        ecosystem=Ecosystem.NODE,
        dependencies=[],
        engine_constraints={"node": ">=18"},
        lockfile_present=True,
    )
    mgr.save_manifests([m1, m2])

    # Test history list command
    res_list = runner.invoke(app, ["history", "list"])
    assert res_list.exit_code == 0
    assert "app1" in res_list.output or "p1" in res_list.output

    # Test history clear with --path
    res_clear_path = runner.invoke(app, ["history", "clear", "--path", str(p1)])
    assert res_clear_path.exit_code == 0

    # Test history clear all
    res_clear_all = runner.invoke(app, ["history", "clear"])
    assert res_clear_all.exit_code == 0
