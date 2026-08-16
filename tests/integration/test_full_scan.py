from __future__ import annotations

import shutil
from pathlib import Path

from zerogravity.parsers.node_parser import NodeParser
from zerogravity.parsers.python_parser import PythonParser
from zerogravity.resolver.conflict_detector import detect_conflicts
from zerogravity.resolver.models import BinaryProbe, SystemSnapshot


def _make_mock_snapshot(**binary_overrides) -> SystemSnapshot:
    """Create a SystemSnapshot with default healthy binaries."""
    defaults = {
        "node": BinaryProbe(name="node", installed=True, path="/usr/bin/node", version="20.11.0"),
        "npm": BinaryProbe(name="npm", installed=True, path="/usr/bin/npm", version="10.2.4"),
        "python3": BinaryProbe(name="python3", installed=True, path="/usr/bin/python3", version="3.11.5"),
        "git": BinaryProbe(name="git", installed=True, path="/usr/bin/git", version="2.42.0"),
    }
    defaults.update(binary_overrides)
    return SystemSnapshot(binaries=defaults)


def test_full_scan_node_project(tmp_path: Path, node_project_path: Path):
    """End-to-end: parse a Node project and run conflict detection."""
    shutil.copytree(node_project_path, tmp_path / "node_project")
    proj_dir = tmp_path / "node_project"

    parser = NodeParser()
    assert parser.can_parse(proj_dir)
    manifest = parser.parse(proj_dir)

    assert manifest.project_name == "test-node-app"
    assert len(manifest.dependencies) > 0
    assert manifest.lockfile_present is True

    snapshot = _make_mock_snapshot()
    report = detect_conflicts([manifest], snapshot)

    assert report.scanned_projects == 1
    # node >=18.0.0 is satisfied by 20.11.0, so no critical issues
    assert report.critical_count == 0


def test_full_scan_python_project(tmp_path: Path, python_project_path: Path):
    """End-to-end: parse a Python project and run conflict detection."""
    shutil.copytree(python_project_path, tmp_path / "python_project")
    proj_dir = tmp_path / "python_project"

    parser = PythonParser()
    assert parser.can_parse(proj_dir)
    manifest = parser.parse(proj_dir)

    assert manifest.project_name == "test-python-app"
    assert len(manifest.dependencies) > 0

    snapshot = _make_mock_snapshot()
    report = detect_conflicts([manifest], snapshot)

    assert report.scanned_projects == 1


def test_full_scan_empty_directory(tmp_path: Path):
    """Scanning an empty directory finds no manifests."""
    node_parser = NodeParser()
    py_parser = PythonParser()

    assert not node_parser.can_parse(tmp_path)
    assert not py_parser.can_parse(tmp_path)
