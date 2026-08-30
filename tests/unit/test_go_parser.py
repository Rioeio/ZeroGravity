from __future__ import annotations

from pathlib import Path

import pytest

from zerogravity.parsers.base import DependencyType, Ecosystem
from zerogravity.parsers.go_parser import GoParser
from zerogravity.parsers.registry import ParserRegistry, detect_and_parse
from zerogravity.resolver.conflict_detector import detect_conflicts
from zerogravity.resolver.models import BinaryProbe, SystemSnapshot


def test_can_parse_with_go_mod(go_project_path: Path):
    parser = GoParser()
    assert parser.can_parse(go_project_path) is True


def test_can_parse_without_go_mod(tmp_path: Path):
    parser = GoParser()
    assert parser.can_parse(tmp_path) is False


def test_ecosystem_property():
    parser = GoParser()
    assert parser.ecosystem == Ecosystem.GO


def test_parse_direct_dependencies(go_project_path: Path):
    parser = GoParser()
    manifest = parser.parse(go_project_path)

    assert manifest.ecosystem == Ecosystem.GO
    assert manifest.project_name == "example.com/go_project"

    direct_deps = {d.name: d for d in manifest.dependencies if d.source == "go.mod" and not d.metadata.get("indirect")}

    assert "github.com/gin-gonic/gin" in direct_deps
    assert direct_deps["github.com/gin-gonic/gin"].dep_type == DependencyType.PRODUCTION
    assert direct_deps["github.com/gin-gonic/gin"].version_spec == "v1.9.1"

    assert "github.com/google/uuid" in direct_deps
    assert direct_deps["github.com/google/uuid"].dep_type == DependencyType.PRODUCTION
    assert direct_deps["github.com/google/uuid"].version_spec == "v1.6.0"

    assert "github.com/stretchr/testify" in direct_deps
    assert direct_deps["github.com/stretchr/testify"].dep_type == DependencyType.PRODUCTION
    assert direct_deps["github.com/stretchr/testify"].version_spec == "v1.8.4"


def test_parse_engine_constraints(go_project_path: Path):
    parser = GoParser()
    manifest = parser.parse(go_project_path)

    assert manifest.engine_constraints.get("go") == ">=1.21.5"
    assert manifest.metadata.get("go_version") == "1.21.5"


def test_parse_lockfile_detection(go_project_path: Path):
    parser = GoParser()
    manifest = parser.parse(go_project_path)

    assert manifest.lockfile_present is True
    assert manifest.lockfile_path == go_project_path / "go.sum"


def test_parse_resolved_versions(go_project_path: Path):
    parser = GoParser()
    manifest = parser.parse(go_project_path)

    direct_deps = {d.name: d for d in manifest.dependencies if d.source == "go.mod" and not d.metadata.get("indirect")}
    assert direct_deps["github.com/gin-gonic/gin"].resolved_version == "v1.9.1"
    assert direct_deps["github.com/google/uuid"].resolved_version == "v1.6.0"
    assert direct_deps["github.com/stretchr/testify"].resolved_version == "v1.8.4"


def test_parse_transitive_dependencies(go_project_path: Path):
    parser = GoParser()
    manifest = parser.parse(go_project_path)

    transitive_deps = {d.name: d for d in manifest.dependencies if d.metadata.get("transitive") is True}

    assert "golang.org/x/crypto" in transitive_deps
    assert transitive_deps["golang.org/x/crypto"].resolved_version == "v0.18.0"
    assert transitive_deps["golang.org/x/crypto"].metadata.get("indirect") is True

    assert "github.com/davecgh/go-spew" in transitive_deps
    assert transitive_deps["github.com/davecgh/go-spew"].resolved_version == "v1.1.1"
    assert transitive_deps["github.com/davecgh/go-spew"].source == "go.sum"

    assert "github.com/pmezard/go-difflib" in transitive_deps
    assert transitive_deps["github.com/pmezard/go-difflib"].resolved_version == "v1.0.0"
    assert transitive_deps["github.com/pmezard/go-difflib"].source == "go.sum"

    # Project module should not be in dependencies
    all_dep_names = {d.name for d in manifest.dependencies}
    assert "example.com/go_project" not in all_dep_names


def test_parse_single_line_require(tmp_path: Path):
    (tmp_path / "go.mod").write_text(
        """
module example.com/single
go 1.20
require github.com/sirupsen/logrus v1.9.3
require github.com/mattn/go-colorable v0.1.13 // indirect
"""
    )
    parser = GoParser()
    manifest = parser.parse(tmp_path)

    deps = {d.name: d for d in manifest.dependencies}
    assert "github.com/sirupsen/logrus" in deps
    assert deps["github.com/sirupsen/logrus"].version_spec == "v1.9.3"
    assert deps["github.com/sirupsen/logrus"].metadata.get("indirect") is None

    assert "github.com/mattn/go-colorable" in deps
    assert deps["github.com/mattn/go-colorable"].metadata.get("indirect") is True


def test_parse_replace_directives(tmp_path: Path):
    (tmp_path / "go.mod").write_text(
        """
module example.com/app
go 1.21

require (
    example.com/forked v1.0.0
    example.com/local v1.0.0
)

replace (
    example.com/forked => example.com/myfork v1.0.1
    example.com/local => ../localpkg
)
"""
    )
    parser = GoParser()
    manifest = parser.parse(tmp_path)
    deps = {d.name: d for d in manifest.dependencies}

    assert deps["example.com/forked"].metadata.get("replace") == "example.com/myfork v1.0.1"
    assert deps["example.com/local"].metadata.get("replace") == "../localpkg"
    assert deps["example.com/local"].metadata.get("workspace_internal") is True


def test_parse_malformed_go_mod(tmp_path: Path):
    (tmp_path / "go.mod").write_text(
        """
module example.com/broken
require (
    github.com/foo/bar v1.0.0
"""
    )
    parser = GoParser()
    with pytest.raises(ValueError):
        parser.parse(tmp_path)


def test_parse_missing_go_mod(tmp_path: Path):
    parser = GoParser()
    with pytest.raises(FileNotFoundError):
        parser.parse(tmp_path)


def test_parse_workspace(tmp_path: Path):
    (tmp_path / "go.work").write_text(
        """
go 1.21

use (
    ./core
    ./web
)
"""
    )
    core_dir = tmp_path / "core"
    web_dir = tmp_path / "web"
    core_dir.mkdir()
    web_dir.mkdir()

    (core_dir / "go.mod").write_text("module example.com/core\ngo 1.21\n")
    (web_dir / "go.mod").write_text("module example.com/web\ngo 1.21\n")

    parser = GoParser()

    # Workspace root
    root_manifest = parser.parse(core_dir)
    assert root_manifest.is_workspace_member is True
    assert root_manifest.workspace_root == tmp_path


def test_registry_integration(go_project_path: Path):
    registry = ParserRegistry()
    parsers = registry.detect_parsers(go_project_path)
    assert any(isinstance(p, GoParser) for p in parsers)

    manifests = detect_and_parse(go_project_path, use_cache=False)
    assert len(manifests) == 1
    assert manifests[0].ecosystem == Ecosystem.GO
    assert manifests[0].project_name == "example.com/go_project"


def test_conflict_detector_with_go_manifest(go_project_path: Path):
    manifests = detect_and_parse(go_project_path, use_cache=False)
    assert len(manifests) == 1
    manifest = manifests[0]

    # Satisfied go version
    snapshot_ok = SystemSnapshot(
        binaries={"go": BinaryProbe(name="go", installed=True, version="1.21.5", path="/usr/bin/go")}
    )
    report_ok = detect_conflicts([manifest], snapshot_ok, include_history=False)
    go_issues = [i for i in report_ok.issues if i.affected_binary == "go"]
    assert len(go_issues) == 0

    # Missing go binary
    snapshot_missing = SystemSnapshot(
        binaries={"go": BinaryProbe(name="go", installed=False)}
    )
    report_missing = detect_conflicts([manifest], snapshot_missing, include_history=False)
    go_issues_missing = [i for i in report_missing.issues if i.affected_binary == "go"]
    assert len(go_issues_missing) == 1
    assert go_issues_missing[0].expected == ">=1.21.5"
