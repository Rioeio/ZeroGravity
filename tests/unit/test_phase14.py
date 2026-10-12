from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from zerogravity.cli import app
from zerogravity.dedup.engine import DeduplicationEngine


def test_atomic_restore_failure_preserves_original_link(tmp_path: Path) -> None:
    """If restoring fails during copy/staging, the original link must remain untouched."""
    engine = DeduplicationEngine(store_path=tmp_path / "store", db_path=tmp_path / "registry.db")
    target_dir = tmp_path / "node_modules" / "test-pkg"
    target_dir.mkdir(parents=True)
    (target_dir / "index.js").write_text("console.log('original');")

    res = engine.optimize(target_dir)
    assert res.status == "success"
    assert engine.linker.is_link(target_dir)

    # Simulate copy failure during restore
    with patch("shutil.copytree", side_effect=OSError("Disk full")):
        result = engine.restore(target_dir)
        assert result.status == "error"

    # In regression, the original link was removed before copy, so it is gone!
    # With atomic restore, the original link MUST still be present and valid.
    assert engine.linker.is_link(target_dir), "Original link was deleted despite restore failure!"
    assert (target_dir / "index.js").read_text() == "console.log('original');"


def test_store_directory_permissions_readonly(tmp_path: Path) -> None:
    """Store directories and subdirectories must be made read-only (0o555)."""
    engine = DeduplicationEngine(store_path=tmp_path / "store", db_path=tmp_path / "registry.db")
    target_dir = tmp_path / "node_modules" / "test-pkg"
    (target_dir / "subdir").mkdir(parents=True)
    (target_dir / "subdir" / "index.js").write_text("console.log('test');")

    chmod_calls: list[tuple[str, int]] = []
    original_chmod = os.chmod

    def mock_chmod(path: str | os.PathLike, mode: int, **kwargs):
        chmod_calls.append((str(path), mode))
        return original_chmod(path, mode, **kwargs)

    with patch("os.chmod", side_effect=mock_chmod):
        res = engine.optimize(target_dir)
        assert res.status == "success"

    # Verify that directories were chmod'd with 0o555
    dir_chmods = [mode for path, mode in chmod_calls if Path(path).is_dir()]
    assert any(mode == 0o555 for mode in dir_chmods), f"Expected directory chmod 0o555, got: {dir_chmods}"


def test_dedup_verify_detects_corrupt_entries(tmp_path: Path) -> None:
    """zg dedup verify detects tampered store files and reports corrupted hash."""
    engine = DeduplicationEngine(store_path=tmp_path / "store", db_path=tmp_path / "registry.db")
    target_dir = tmp_path / "node_modules" / "test-pkg"
    target_dir.mkdir(parents=True)
    (target_dir / "index.js").write_text("console.log('original');")

    res = engine.optimize(target_dir)
    assert res.status == "success"
    assert res.store_path is not None
    store_file = res.store_path / "index.js"

    # Tamper with the store file (restore write permission first to simulate unauthorized alteration)
    os.chmod(store_file, 0o644)
    store_file.write_text("console.log('tampered');")

    runner = CliRunner()
    result = runner.invoke(app, ["dedup", "verify", "--store", str(tmp_path / "store"), "--db", str(tmp_path / "registry.db")])
    assert result.exit_code == 1
    assert "corrupt" in result.stdout.lower() or "mismatch" in result.stdout.lower()


def test_cleanup_propagates_deletion_errors(tmp_path: Path) -> None:
    """Cleanup of orphaned store entries must not silently swallow deletion errors with ignore_errors=True."""
    from zerogravity.dedup.cleanup import cleanup_orphaned_store

    store_dir = tmp_path / "store"
    store_dir.mkdir()
    orphan_dir = store_dir / "fake_orphan_hash"
    orphan_dir.mkdir()
    (orphan_dir / "file.txt").write_text("orphan")

    engine = DeduplicationEngine(store_path=store_dir, db_path=tmp_path / "registry.db")

    with patch("shutil.rmtree", side_effect=PermissionError("Permission denied")):
        result = cleanup_orphaned_store(engine)
        assert result["failed"] > 0
        assert len(result["errors"]) > 0


def test_dedup_verify_repair(tmp_path: Path) -> None:
    """--repair unlinks and purges corrupted store entries."""
    engine = DeduplicationEngine(store_path=tmp_path / "store", db_path=tmp_path / "registry.db")
    target_dir = tmp_path / "node_modules" / "test-pkg"
    target_dir.mkdir(parents=True)
    (target_dir / "index.js").write_text("console.log('original');")

    res = engine.optimize(target_dir)
    assert res.status == "success"
    assert res.store_path is not None
    store_file = res.store_path / "index.js"

    # Corrupt store file
    os.chmod(store_file, 0o644)
    store_file.write_text("console.log('corrupted');")

    runner = CliRunner()
    repair_res = runner.invoke(app, ["dedup", "verify", "--repair", "--store", str(tmp_path / "store"), "--db", str(tmp_path / "registry.db")])
    assert repair_res.exit_code == 0
    assert "repaired" in repair_res.stdout.lower()

    # Re-verify is now clean
    verify_res = runner.invoke(app, ["dedup", "verify", "--store", str(tmp_path / "store"), "--db", str(tmp_path / "registry.db")])
    assert verify_res.exit_code == 0
    assert "clean" in verify_res.stdout.lower()


def test_real_symlink_roundtrip(tmp_path: Path) -> None:
    """Test full optimize and restore roundtrip."""
    engine = DeduplicationEngine(store_path=tmp_path / "store", db_path=tmp_path / "registry.db")
    target_dir = tmp_path / "node_modules" / "test-pkg"
    target_dir.mkdir(parents=True)
    (target_dir / "app.js").write_text("console.log('hello roundtrip');")

    opt_res = engine.optimize(target_dir)
    if opt_res.status == "error" and "privilege" in (opt_res.error_message or "").lower():
        pytest.skip("Symlink creation requires elevated privileges on Windows")

    assert opt_res.status == "success"
    assert engine.linker.is_link(target_dir)

    restore_res = engine.restore(target_dir)
    assert restore_res.status == "success"
    assert not engine.linker.is_link(target_dir)
    assert (target_dir / "app.js").read_text() == "console.log('hello roundtrip');"

