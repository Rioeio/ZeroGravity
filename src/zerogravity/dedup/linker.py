from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional


@dataclass
class LinkResult:
    status: str  # "success", "error", "fallback"
    method: str  # "junction", "symlink", "hardlink"
    error_message: Optional[str] = None

class CrossPlatformLinker:
    """Handles cross-platform file and directory linking (symlinks, junctions, hardlinks)."""

    def create_link(self, target: Path, link_path: Path) -> LinkResult:
        """Create a link from link_path to target."""
        target = target.absolute()
        link_path = link_path.absolute()

        if sys.platform == "win32":
            try:
                # Primary: Use Junction Points via cmd mklink /J
                result = subprocess.run(
                    ["cmd", "/c", "mklink", "/J", str(link_path), str(target)],
                    capture_output=True, text=True
                )
                if result.returncode == 0:
                    return LinkResult("success", "junction")
            except Exception:
                pass

            # Fallback: Try os.symlink
            try:
                os.symlink(target, link_path, target_is_directory=target.is_dir())
                return LinkResult("fallback", "symlink")
            except Exception as e:
                return LinkResult("error", "none", f"Failed to create link: {e}")

        else:
            try:
                os.symlink(target, link_path)
                return LinkResult("success", "symlink")
            except Exception as e:
                return LinkResult("error", "none", f"Failed to create symlink: {e}")

    def is_link(self, path: Path) -> bool:
        """Check if a path is a symlink or junction point."""
        if sys.platform == "win32":
            try:
                st = os.lstat(path)
                import stat
                if hasattr(st, "st_file_attributes") and (st.st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT):
                    return True
            except (OSError, ValueError):
                pass
        if not path.exists() and not path.is_symlink():
            return False
        return path.is_symlink() or os.path.islink(path)

    def resolve_link(self, path: Path) -> Optional[Path]:
        """Return the real target of a symlink/junction, or None if not a link."""
        if self.is_link(path):
            return path.resolve()
        return None

    def remove_link(self, path: Path) -> bool:
        """Safely removes a symlink/junction without deleting the target."""
        if not self.is_link(path):
            return False

        try:
            # First attempt to fix permissions if it's read-only
            if sys.platform == "win32":
                import stat
                try:
                    os.chmod(path, stat.S_IWRITE)
                except Exception:
                    pass

            if sys.platform == "win32" and path.is_dir():
                os.rmdir(path)
            else:
                path.unlink()
            return True
        except Exception:
            return False

    def check_same_volume(self, path_a: Path, path_b: Path) -> bool:
        """Checks if two paths are on the same filesystem/volume."""
        if not path_a.exists() and not path_a.parent.exists():
            return False

        try:
            if sys.platform == "win32":
                return path_a.absolute().drive.lower() == path_b.absolute().drive.lower()

            stat_a = path_a.stat().st_dev if path_a.exists() else path_a.parent.stat().st_dev
            stat_b = path_b.stat().st_dev if path_b.exists() else path_b.parent.stat().st_dev
            return stat_a == stat_b
        except Exception:
            return False

def detect_link_capabilities() -> Dict[str, bool]:
    """Checks which linking methods are available on the current OS."""
    capabilities = {
        "symlinks_available": False,
        "junctions_available": False,
        "hardlinks_available": False
    }

    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        target_file = temp_path / "target.txt"
        target_file.write_text("test")
        target_dir = temp_path / "target_dir"
        target_dir.mkdir()

        # Test hardlinks
        hardlink_path = temp_path / "hardlink.txt"
        try:
            os.link(target_file, hardlink_path)
            capabilities["hardlinks_available"] = True
        except Exception:
            pass

        # Test symlinks
        symlink_path = temp_path / "symlink.txt"
        try:
            os.symlink(target_file, symlink_path)
            capabilities["symlinks_available"] = True
        except Exception:
            pass

        # Test junctions (Windows only)
        if sys.platform == "win32":
            junction_path = temp_path / "junction_dir"
            try:
                result = subprocess.run(
                    ["cmd", "/c", "mklink", "/J", str(junction_path), str(target_dir)],
                    capture_output=True
                )
                capabilities["junctions_available"] = (result.returncode == 0)
            except Exception:
                pass

    return capabilities
