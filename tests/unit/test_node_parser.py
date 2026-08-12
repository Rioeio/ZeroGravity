from __future__ import annotations
import pytest
from pathlib import Path
from zerogravity.parsers.node_parser import NodeParser
from zerogravity.parsers.base import DependencyType

def test_can_parse_with_package_json(node_project_path: Path):
    parser = NodeParser()
    assert parser.can_parse(node_project_path) is True

def test_can_parse_without_package_json(tmp_path: Path):
    parser = NodeParser()
    assert parser.can_parse(tmp_path) is False

def test_parse_dependencies(node_project_path: Path):
    parser = NodeParser()
    manifest = parser.parse(node_project_path)
    deps = {d.name: d for d in manifest.dependencies}
    assert "express" in deps
    assert deps["express"].dep_type == DependencyType.PRODUCTION
    assert deps["jest"].dep_type == DependencyType.DEVELOPMENT
    assert deps["react"].dep_type == DependencyType.PEER
    assert deps["fsevents"].dep_type == DependencyType.OPTIONAL

def test_parse_engine_constraints(node_project_path: Path):
    parser = NodeParser()
    manifest = parser.parse(node_project_path)
    assert manifest.engine_constraints["node"] == ">=18.0.0"

def test_parse_lockfile_detection(node_project_path: Path):
    parser = NodeParser()
    manifest = parser.parse(node_project_path)
    assert manifest.lockfile_present is True
    assert manifest.lockfile_path == str(node_project_path / "package-lock.json")

def test_parse_resolved_versions(node_project_path: Path):
    parser = NodeParser()
    manifest = parser.parse(node_project_path)
    deps = {d.name: d for d in manifest.dependencies}
    assert deps["express"].resolved_version == "4.18.2"

def test_parse_empty_dependencies(tmp_path: Path):
    pkg = tmp_path / "package.json"
    pkg.write_text('{"name": "empty"}')
    parser = NodeParser()
    manifest = parser.parse(tmp_path)
    assert len(manifest.dependencies) == 0

def test_parse_malformed_json(tmp_path: Path):
    pkg = tmp_path / "package.json"
    pkg.write_text('{malformed')
    parser = NodeParser()
    with pytest.raises(ValueError):
        parser.parse(tmp_path)
