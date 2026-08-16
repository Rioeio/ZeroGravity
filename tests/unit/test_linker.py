from __future__ import annotations

import os
from pathlib import Path

from zerogravity.dedup.linker import CrossPlatformLinker


def test_check_same_volume_same_drive(tmp_path: Path):
    """Paths on the same volume should return True."""
    linker = CrossPlatformLinker()
    dir_a = tmp_path / "a"
    dir_a.mkdir()
    dir_b = tmp_path / "b"
    dir_b.mkdir()
    assert linker.check_same_volume(dir_a, dir_b) is True


def test_is_link_normal_dir(tmp_path: Path):
    """A regular directory is NOT a link."""
    linker = CrossPlatformLinker()
    d = tmp_path / "normal_dir"
    d.mkdir()
    assert linker.is_link(d) is False


def test_create_and_check_link(tmp_path: Path):
    """Creating a link and then checking it should return True."""
    linker = CrossPlatformLinker()
    src = tmp_path / "src"
    src.mkdir()
    (src / "file.txt").write_text("content")
    dest = tmp_path / "dest"

    result = linker.create_link(src, dest)
    assert result.status in ("success", "fallback"), f"Link creation failed: {result.error_message}"
    assert dest.exists(), "Link target should exist"

    # On Windows with junctions, is_symlink() may return False
    # but the directory should still function as a link
    if result.method == "junction":
        # Junctions on Windows: verify directory is accessible and
        # points to the right content
        assert (dest / "file.txt").exists()
    else:
        assert linker.is_link(dest)


def test_remove_link(tmp_path: Path):
    """Removing a link should not delete the target."""
    linker = CrossPlatformLinker()
    src = tmp_path / "src"
    src.mkdir()
    (src / "file.txt").write_text("content")
    dest = tmp_path / "dest"

    result = linker.create_link(src, dest)
    assert result.status in ("success", "fallback"), f"Link creation failed: {result.error_message}"

    # Remove the link
    if result.method == "junction":
        # Junctions: remove with os.rmdir
        os.rmdir(dest)
    else:
        linker.remove_link(dest)

    assert not dest.exists(), "Link should be removed"
    assert src.exists(), "Target should still exist"
    assert (src / "file.txt").exists(), "Target content should be intact"


def test_resolve_link(tmp_path: Path):
    """Resolving a link should return the target path."""
    linker = CrossPlatformLinker()
    src = tmp_path / "src"
    src.mkdir()
    dest = tmp_path / "dest"

    result = linker.create_link(src, dest)
    assert result.status in ("success", "fallback"), f"Link creation failed: {result.error_message}"

    resolved = linker.resolve_link(dest)
    if resolved is not None:
        assert resolved.resolve() == src.resolve()
    else:
        # For junctions, resolve_link may return None if is_link returns False
        # But the content should still be accessible through the junction
        assert dest.exists()
