from __future__ import annotations

import os
import time
from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

from zerogravity.cli import app
from zerogravity.parsers.base import Dependency, DependencyType, Ecosystem, ProjectManifest
from zerogravity.parsers.node_parser import NodeParser
from zerogravity.parsers.registry import detect_and_parse
from zerogravity.scanner.cache import (
    ScanCacheManager,
    dict_to_manifest,
    manifest_to_dict,
)

runner = CliRunner()


def test_manifest_serialization_roundtrip():
    """Verify ProjectManifest serializes to dict and deserializes faithfully."""
    dep = Dependency(
        name="express",
        version_spec="^4.18.2",
        resolved_version="4.18.2",
        dep_type=DependencyType.PRODUCTION,
        extras=["security"],
        source="package.json",
        metadata={"workspace_internal": False},
    )
    original = ProjectManifest(
        project_path=Path("/tmp/my-proj"),
        project_name="my-proj",
        ecosystem=Ecosystem.NODE,
        dependencies=[dep],
        engine_constraints={"node": ">=18.0.0"},
        lockfile_present=True,
        lockfile_path=Path("/tmp/my-proj/package-lock.json"),
        manifest_files=[Path("/tmp/my-proj/package.json")],
        metadata={"custom": "value"},
        workspace_root=Path("/tmp/my-proj"),
        workspace_members=[Path("/tmp/my-proj/packages/a")],
        is_workspace_root=True,
        is_workspace_member=False,
    )

    data = manifest_to_dict(original)
    restored = dict_to_manifest(data)

    assert restored.project_path == original.project_path
    assert restored.project_name == original.project_name
    assert restored.ecosystem == original.ecosystem
    assert len(restored.dependencies) == 1
    assert restored.dependencies[0].name == "express"
    assert restored.dependencies[0].resolved_version == "4.18.2"
    assert restored.dependencies[0].dep_type == DependencyType.PRODUCTION
    assert restored.engine_constraints == {"node": ">=18.0.0"}
    assert restored.lockfile_present is True
    assert restored.is_workspace_root is True
    assert restored.workspace_members == [Path("/tmp/my-proj/packages/a")]


def test_benchmark_second_scan_zero_lockfile_reparses(tmp_path: Path):
    """
    Benchmark test: A second scan on an unchanged fixture does zero lockfile re-parses.
    """
    cache_file = tmp_path / "cache.json"
    cache_mgr = ScanCacheManager(cache_file=cache_file)

    proj_dir = tmp_path / "app"
    proj_dir.mkdir()
    (proj_dir / "package.json").write_text('{"name": "benchmark-app", "dependencies": {"lodash": "^4.17.21"}}')
    (proj_dir / "package-lock.json").write_text("""{
  "name": "benchmark-app",
  "version": "1.0.0",
  "lockfileVersion": 3,
  "packages": {
    "": { "name": "benchmark-app", "dependencies": { "lodash": "^4.17.21" } },
    "node_modules/lodash": { "version": "4.17.21" }
  }
}""")

    # First scan: cache miss, parses from disk
    manifests_1 = detect_and_parse(proj_dir, use_cache=True, cache_manager=cache_mgr)
    assert len(manifests_1) == 1
    assert manifests_1[0].dependencies[0].name == "lodash"
    assert cache_file.exists()

    # Second scan: cache hit, zero calls to NodeParser.parse
    with patch.object(NodeParser, "parse", wraps=NodeParser().parse) as mock_parse:
        manifests_2 = detect_and_parse(proj_dir, use_cache=True, cache_manager=cache_mgr)
        assert len(manifests_2) == 1
        assert manifests_2[0].project_name == "benchmark-app"
        assert manifests_2[0].dependencies[0].name == "lodash"
        # Zero lockfile / manifest re-parses
        mock_parse.assert_not_called()


def test_cache_invalidates_when_lockfile_touched(tmp_path: Path):
    """Touching a lockfile (updating mtime) invalidates the scan cache."""
    cache_file = tmp_path / "cache.json"
    cache_mgr = ScanCacheManager(cache_file=cache_file)

    proj_dir = tmp_path / "app"
    proj_dir.mkdir()
    (proj_dir / "package.json").write_text('{"name": "touch-app"}')
    lock_file = proj_dir / "package-lock.json"
    lock_file.write_text('{"lockfileVersion": 3, "packages": {}}')

    # Initial scan populates cache
    detect_and_parse(proj_dir, use_cache=True, cache_manager=cache_mgr)

    # Touch the lockfile by updating mtime into the future
    future_time = time.time() + 100
    os.utime(lock_file, (future_time, future_time))

    # Next scan should invalidate cache and re-parse
    with patch.object(NodeParser, "parse", wraps=NodeParser().parse) as mock_parse:
        manifests = detect_and_parse(proj_dir, use_cache=True, cache_manager=cache_mgr)
        assert len(manifests) == 1
        mock_parse.assert_called_once()


def test_cache_invalidates_when_lockfile_content_changed(tmp_path: Path):
    """Changing lockfile content invalidates the scan cache."""
    cache_file = tmp_path / "cache.json"
    cache_mgr = ScanCacheManager(cache_file=cache_file)

    proj_dir = tmp_path / "app"
    proj_dir.mkdir()
    (proj_dir / "package.json").write_text('{"name": "content-app"}')
    lock_file = proj_dir / "package-lock.json"
    lock_file.write_text('{"lockfileVersion": 3, "packages": {}}')

    # Initial scan
    detect_and_parse(proj_dir, use_cache=True, cache_manager=cache_mgr)

    # Modify content
    lock_file.write_text('{"lockfileVersion": 3, "packages": {"node_modules/foo": {"version": "1.0.0"}}}')

    with patch.object(NodeParser, "parse", wraps=NodeParser().parse) as mock_parse:
        manifests = detect_and_parse(proj_dir, use_cache=True, cache_manager=cache_mgr)
        assert len(manifests) == 1
        mock_parse.assert_called_once()


def test_cache_invalidates_when_manifest_content_changed(tmp_path: Path):
    """Changing package.json content invalidates the scan cache."""
    cache_file = tmp_path / "cache.json"
    cache_mgr = ScanCacheManager(cache_file=cache_file)

    proj_dir = tmp_path / "app"
    proj_dir.mkdir()
    pkg_file = proj_dir / "package.json"
    pkg_file.write_text('{"name": "original-name"}')

    detect_and_parse(proj_dir, use_cache=True, cache_manager=cache_mgr)

    # Change package.json
    pkg_file.write_text('{"name": "updated-name"}')

    manifests = detect_and_parse(proj_dir, use_cache=True, cache_manager=cache_mgr)
    assert manifests[0].project_name == "updated-name"


def test_no_cache_cli_flag(tmp_path: Path):
    """--no-cache flag forces full rescan even when cache exists."""
    proj_dir = tmp_path / "app"
    proj_dir.mkdir()
    (proj_dir / "package.json").write_text('{"name": "cli-cache-app"}')

    # Run scan with cache enabled (creates cache)
    res1 = runner.invoke(app, ["scan", str(proj_dir)])
    assert res1.exit_code == 0

    # Run scan with --no-cache
    res2 = runner.invoke(app, ["scan", str(proj_dir), "--no-cache"])
    assert res2.exit_code == 0
    assert "cli-cache-app" in res2.stdout
