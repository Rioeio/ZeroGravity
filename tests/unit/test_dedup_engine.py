from __future__ import annotations

import pytest
from pathlib import Path
from zerogravity.dedup.engine import DeduplicationEngine


def test_generate_content_hash_deterministic(tmp_path: Path):
    """Same directory content produces the same hash."""
    target_dir = tmp_path / "pkg"
    target_dir.mkdir()
    (target_dir / "test.txt").write_text("hello world")

    engine = DeduplicationEngine(
        store_path=tmp_path / "store", db_path=tmp_path / "registry.db"
    )
    hash1 = engine._generate_content_hash(target_dir)
    hash2 = engine._generate_content_hash(target_dir)
    assert hash1 == hash2


def test_generate_content_hash_different(tmp_path: Path):
    """Different directory content produces different hashes."""
    dir1 = tmp_path / "pkg1"
    dir1.mkdir()
    (dir1 / "test.txt").write_text("hello world")

    dir2 = tmp_path / "pkg2"
    dir2.mkdir()
    (dir2 / "test.txt").write_text("goodbye world")

    engine = DeduplicationEngine(
        store_path=tmp_path / "store", db_path=tmp_path / "registry.db"
    )
    assert engine._generate_content_hash(dir1) != engine._generate_content_hash(dir2)


def test_optimize_creates_link(tmp_path: Path):
    """Optimizing a directory moves it to store and creates a link."""
    engine = DeduplicationEngine(
        store_path=tmp_path / "store", db_path=tmp_path / "registry.db"
    )
    target_dir = tmp_path / "node_modules" / "test-pkg"
    target_dir.mkdir(parents=True)
    (target_dir / "index.js").write_text("console.log('test');")

    result = engine.optimize(target_dir)
    assert result.status == "success"
    assert engine.linker.is_link(target_dir)


def test_optimize_skips_symlink(tmp_path: Path):
    """Optimizing an already-linked directory returns 'skipped'."""
    engine = DeduplicationEngine(
        store_path=tmp_path / "store", db_path=tmp_path / "registry.db"
    )
    target_dir = tmp_path / "node_modules" / "test-pkg"
    target_dir.mkdir(parents=True)
    (target_dir / "index.js").write_text("console.log('test');")

    engine.optimize(target_dir)
    result = engine.optimize(target_dir)
    assert result.status == "skipped"


def test_optimize_nonexistent_path(tmp_path: Path):
    """Optimizing a nonexistent path returns 'error'."""
    engine = DeduplicationEngine(
        store_path=tmp_path / "store", db_path=tmp_path / "registry.db"
    )
    result = engine.optimize(tmp_path / "does-not-exist")
    assert result.status == "error"
    assert result.error_message is not None


def test_restore_reverses_optimization(tmp_path: Path):
    """Restore undoes an optimization, turning the link back into a real directory."""
    engine = DeduplicationEngine(
        store_path=tmp_path / "store", db_path=tmp_path / "registry.db"
    )
    target_dir = tmp_path / "node_modules" / "test-pkg"
    target_dir.mkdir(parents=True)
    (target_dir / "index.js").write_text("console.log('test');")

    engine.optimize(target_dir)
    assert engine.linker.is_link(target_dir)

    result = engine.restore(target_dir)
    assert result.status == "success"
    assert not engine.linker.is_link(target_dir)
    assert target_dir.is_dir()


def test_scan_for_duplicates(tmp_path: Path):
    """Scanning two projects with identical packages finds duplicates."""
    engine = DeduplicationEngine(
        store_path=tmp_path / "store", db_path=tmp_path / "registry.db"
    )
    # Create identical packages in two projects
    for proj_name in ["proj1", "proj2"]:
        pkg = tmp_path / proj_name / "node_modules"
        pkg.mkdir(parents=True)
        (pkg / "index.js").write_text("console.log('test');")

    report = engine.scan_for_duplicates(
        [tmp_path / "proj1", tmp_path / "proj2"]
    )
    assert report.total_directories >= 2
    assert len(report.groups) > 0
    assert report.total_waste_bytes > 0
