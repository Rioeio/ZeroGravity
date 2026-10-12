from __future__ import annotations

import hashlib
import logging
import os
import shutil
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from zerogravity.dedup.linker import CrossPlatformLinker
from zerogravity.dedup.registry import DeduplicationRegistry

logger = logging.getLogger(__name__)


def make_store_readonly(path: Path) -> None:
    """Make store files read-only (0o444) and subdirectories read-only (0o555)."""
    for root, dirs, files in os.walk(path, topdown=False):
        for file in files:
            try:
                os.chmod(os.path.join(root, file), 0o444)
            except OSError as err:
                logger.debug("Failed chmod on %s: %s", file, err)
        for d in dirs:
            try:
                os.chmod(os.path.join(root, d), 0o555)
            except OSError as err:
                logger.debug("Failed chmod on dir %s: %s", d, err)
    try:
        os.chmod(path, 0o555)
    except OSError as err:
        logger.debug("Failed chmod on root store dir %s: %s", path, err)


def make_store_writable(path: Path) -> None:
    """Restore write permissions to store files (0o644) and directories (0o755)."""
    try:
        os.chmod(path, 0o755)
    except OSError:
        pass
    for root, dirs, files in os.walk(path):
        for d in dirs:
            try:
                os.chmod(os.path.join(root, d), 0o755)
            except OSError:
                pass
        for f in files:
            try:
                os.chmod(os.path.join(root, f), 0o644)
            except OSError:
                pass


@contextmanager
def writable_store_package(path: Path):
    """Context manager to temporarily restore write permissions to a store package."""
    make_store_writable(path)
    try:
        yield
    finally:
        if path.exists():
            make_store_readonly(path)


@dataclass
class OptimizationResult:
    status: str
    hash: Optional[str]
    bytes_saved: int
    link_path: Optional[Path]
    store_path: Optional[Path]
    error_message: Optional[str] = None

@dataclass
class RestoreResult:
    status: str
    original_path: Path
    error_message: Optional[str] = None

@dataclass
class DuplicateGroup:
    hash: str
    paths: List[Path]
    size_bytes: int
    potential_savings: int

@dataclass
class DuplicateReport:
    groups: List[DuplicateGroup]
    total_waste_bytes: int
    total_directories: int

def _get_logical_project_root(path: Path) -> Path:
    """Determine the logical project / workspace root for a given path."""
    current = path.resolve()
    if current.is_file():
        current = current.parent

    # Climb up to find any workspace root or project manifest
    scan_cursor = current
    while scan_cursor != scan_cursor.parent:
        pkg_json = scan_cursor / "package.json"
        pnpm_ws = scan_cursor / "pnpm-workspace.yaml"
        pyproject = scan_cursor / "pyproject.toml"

        if pnpm_ws.is_file():
            return scan_cursor

        if pkg_json.is_file():
            try:
                import json
                with open(pkg_json, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if "workspaces" in data:
                    return scan_cursor
            except (json.JSONDecodeError, OSError) as err:
                logger.debug("Failed reading %s: %s", pkg_json, err, exc_info=True)

        if pyproject.is_file():
            try:
                import tomllib
                with open(pyproject, "rb") as f:
                    data = tomllib.load(f)
                if "tool" in data and isinstance(data["tool"], dict):
                    uv_ws = data["tool"].get("uv", {})
                    if isinstance(uv_ws, dict) and "workspace" in uv_ws:
                        return scan_cursor
            except (tomllib.TOMLDecodeError, OSError) as err:
                logger.debug("Failed reading %s: %s", pyproject, err, exc_info=True)

        if (scan_cursor / ".git").is_dir():
            break
        scan_cursor = scan_cursor.parent

    # Fallback to nearest directory containing any manifest
    scan_cursor = current
    while scan_cursor != scan_cursor.parent:
        if (
            (scan_cursor / "package.json").is_file()
            or (scan_cursor / "pyproject.toml").is_file()
            or (scan_cursor / "requirements.txt").is_file()
            or (scan_cursor / "Pipfile").is_file()
        ):
            return scan_cursor
        if (scan_cursor / ".git").is_dir():
            break
        scan_cursor = scan_cursor.parent

    return current


class DeduplicationEngine:
    """The main deduplication engine for ZeroGravity."""

    def __init__(self, store_path: Optional[Path] = None, db_path: Optional[Path] = None):
        if store_path is None:
            self.store_path = Path.home() / ".zerogravity" / "store"
        else:
            self.store_path = Path(store_path)

        self.store_path.mkdir(parents=True, exist_ok=True)

        self.linker = CrossPlatformLinker()
        self.registry = DeduplicationRegistry(db_path)

    def _generate_content_hash(self, path: Path) -> str:
        """Generates a SHA-256 hash based on the directory contents."""
        hasher = hashlib.sha256()

        manifest = []
        for root, _, files in os.walk(path):
            for file in files:
                file_path = Path(root) / file
                try:
                    rel_path = file_path.relative_to(path)
                    stat = file_path.stat()
                    file_hasher = hashlib.sha256()
                    with open(file_path, "rb") as f:
                        while chunk := f.read(65536):
                            file_hasher.update(chunk)
                    manifest.append((str(rel_path), stat.st_size, file_hasher.hexdigest()))
                except (OSError, RuntimeError) as err:
                    logger.debug("Failed hashing %s: %s", file_path, err, exc_info=True)
                    continue

        # Sort for determinism
        manifest.sort(key=lambda x: x[0])

        for item in manifest:
            hasher.update(f"{item[0]}:{item[1]}:{item[2]}".encode('utf-8'))

        return hasher.hexdigest()

    def _get_dir_size(self, path: Path) -> int:
        """Calculate total size of a directory."""
        total_size = 0
        for dirpath, _, filenames in os.walk(path):
            for f in filenames:
                fp = os.path.join(dirpath, f)
                if not os.path.islink(fp):
                    total_size += os.path.getsize(fp)
        return total_size

    def _count_files(self, path: Path) -> int:
        """Count total files in a directory."""
        count = 0
        for _, _, filenames in os.walk(path):
            count += len(filenames)
        return count

    def optimize(self, dep_path: Path) -> OptimizationResult:
        """Optimize a dependency directory by deduplicating it."""
        dep_path = dep_path.absolute()

        if not dep_path.exists():
            return OptimizationResult("error", None, 0, None, None, "Path does not exist")
        if not dep_path.is_dir():
            return OptimizationResult("error", None, 0, None, None, "Path is not a directory")
        if self.linker.is_link(dep_path):
            return OptimizationResult("skipped", None, 0, None, None, "Path is already a link")

        if not self.linker.check_same_volume(dep_path, self.store_path):
            return OptimizationResult("error", None, 0, None, None, "Path and store are on different volumes")

        dir_hash = self._generate_content_hash(dep_path)
        store_package_path = self.store_path / dir_hash
        dir_size = self._get_dir_size(dep_path)
        file_count = self._count_files(dep_path)

        try:
            if self.registry.package_exists(dir_hash):
                # Package already in store, replace with link
                temp_path = dep_path.with_name(f"{dep_path.name}.bak")
                shutil.move(str(dep_path), str(temp_path))

                link_result = self.linker.create_link(store_package_path, dep_path)
                if link_result.status == "error":
                    # Rollback
                    shutil.move(str(temp_path), str(dep_path))
                    return OptimizationResult("error", dir_hash, 0, None, None, link_result.error_message)

                from zerogravity.dedup.cleanup import handle_remove_readonly
                shutil.rmtree(temp_path, onerror=handle_remove_readonly)
                bytes_saved = dir_size

            else:
                # Move to store and create link
                shutil.move(str(dep_path), str(store_package_path))

                # Make store files (0o444) and directories (0o555) read-only
                make_store_readonly(store_package_path)

                link_result = self.linker.create_link(store_package_path, dep_path)
                if link_result.status == "error":
                    # Rollback
                    make_store_writable(store_package_path)
                    shutil.move(str(store_package_path), str(dep_path))
                    return OptimizationResult("error", dir_hash, 0, None, None, link_result.error_message)

                self.registry.register_package(dir_hash, str(store_package_path), dir_size, file_count)
                bytes_saved = 0 # No space saved on first ingestion

            self.registry.register_link(dir_hash, str(dep_path), str(dep_path.parent), str(dep_path))

            return OptimizationResult("success", dir_hash, bytes_saved, dep_path, store_package_path)

        except (OSError, RuntimeError, shutil.Error) as e:
            return OptimizationResult("error", dir_hash, 0, None, None, str(e))

    def restore(self, dep_path: Path) -> RestoreResult:
        """Restore a linked dependency back to a physical copy using atomic staging and replacement."""
        dep_path = dep_path.absolute()

        if not self.linker.is_link(dep_path):
            return RestoreResult("error", dep_path, "Path is not a managed link")

        target_path = self.linker.resolve_link(dep_path)
        if not target_path or not target_path.exists():
            return RestoreResult("error", dep_path, "Link target does not exist")

        # Stage restored copy in temporary sibling directory to avoid corrupting link on copy failure
        temp_stage = dep_path.parent / f".{dep_path.name}.restore_tmp_{uuid.uuid4().hex[:8]}"
        try:
            shutil.copytree(target_path, temp_stage)
            for root, dirs, files in os.walk(temp_stage):
                for d in dirs:
                    try:
                        os.chmod(os.path.join(root, d), 0o755)
                    except OSError:
                        pass
                for f in files:
                    try:
                        os.chmod(os.path.join(root, f), 0o644)
                    except OSError:
                        pass
        except (OSError, RuntimeError, shutil.Error) as err:
            if temp_stage.exists():
                from zerogravity.dedup.cleanup import handle_remove_readonly
                shutil.rmtree(temp_stage, onerror=handle_remove_readonly)
            return RestoreResult("error", dep_path, f"Failed staging restored package: {err}")

        # Atomic replacement of link with staged directory
        try:
            if os.name != "nt":
                os.replace(str(temp_stage), str(dep_path))
            else:
                if not self.linker.remove_link(dep_path):
                    shutil.rmtree(temp_stage, ignore_errors=True)
                    return RestoreResult("error", dep_path, "Failed to remove link during atomic swap")
                try:
                    os.replace(str(temp_stage), str(dep_path))
                except OSError as swap_err:
                    self.linker.create_link(target_path, dep_path)
                    shutil.rmtree(temp_stage, ignore_errors=True)
                    return RestoreResult("error", dep_path, f"Failed swapping restored directory: {swap_err}")

            self.registry.remove_link(str(dep_path))
            return RestoreResult("success", dep_path)
        except (OSError, RuntimeError, shutil.Error) as e:
            if temp_stage.exists():
                shutil.rmtree(temp_stage, ignore_errors=True)
            return RestoreResult("error", dep_path, str(e))

    def verify_store(self, repair: bool = False) -> dict[str, Any]:
        """Verify the integrity of all packages in the store against content hashes."""
        valid: list[dict[str, Any]] = []
        corrupted: list[dict[str, Any]] = []
        missing: list[dict[str, Any]] = []
        repaired: list[dict[str, Any]] = []

        registered_hashes: set[str] = set()
        conn = self.registry._get_connection()
        try:
            with conn:
                cursor = conn.execute("SELECT hash, store_path, size_bytes FROM packages")
                rows = [dict(r) for r in cursor.fetchall()]
        finally:
            if not self.registry.conn:
                conn.close()

        from zerogravity.dedup.cleanup import handle_remove_readonly

        for row in rows:
            pkg_hash = row["hash"]
            registered_hashes.add(pkg_hash)
            store_pkg_path = Path(row["store_path"])

            if not store_pkg_path.exists():
                missing.append({"hash": pkg_hash, "path": str(store_pkg_path)})
                if repair:
                    for link in self.registry.get_links_for_package(pkg_hash):
                        self.linker.remove_link(Path(link["link_path"]))
                    self.registry.remove_package(pkg_hash)
                    repaired.append({"hash": pkg_hash, "action": "removed_missing_package_and_links"})
                continue

            current_hash = self._generate_content_hash(store_pkg_path)
            if current_hash != pkg_hash:
                corrupted.append({
                    "hash": pkg_hash,
                    "actual_hash": current_hash,
                    "path": str(store_pkg_path),
                })
                if repair:
                    for link in self.registry.get_links_for_package(pkg_hash):
                        self.linker.remove_link(Path(link["link_path"]))
                    self.registry.remove_package(pkg_hash)
                    make_store_writable(store_pkg_path)
                    shutil.rmtree(store_pkg_path, onerror=handle_remove_readonly)
                    repaired.append({"hash": pkg_hash, "action": "purged_corrupted_package_and_links"})
            else:
                valid.append({"hash": pkg_hash, "path": str(store_pkg_path)})

        if self.store_path.exists():
            for child in self.store_path.iterdir():
                if child.is_dir() and child.name not in registered_hashes:
                    calc_hash = self._generate_content_hash(child)
                    if calc_hash != child.name:
                        corrupted.append({
                            "hash": child.name,
                            "actual_hash": calc_hash,
                            "path": str(child),
                        })
                        if repair:
                            make_store_writable(child)
                            shutil.rmtree(child, onerror=handle_remove_readonly)
                            repaired.append({"hash": child.name, "action": "purged_corrupted_untracked_dir"})

        return {
            "valid": valid,
            "corrupted": corrupted,
            "missing": missing,
            "repaired": repaired,
        }

    def scan_for_duplicates(self, project_paths: List[Path], target_dirs: Optional[List[str]] = None) -> DuplicateReport:
        """Scan project paths for duplicate dependency directories."""
        if target_dirs is None:
            target_dirs = ["node_modules", ".venv", "vendor"]

        hash_to_paths: Dict[str, List[Path]] = {}
        hash_to_size: Dict[str, int] = {}
        total_directories = 0

        for proj_path in project_paths:
            for root, dirs, _ in os.walk(proj_path):
                # Prune search tree to avoid deep diving into already matched target_dirs
                dirs[:] = [d for d in dirs if not d.startswith('.')]

                for d in dirs:
                    if d in target_dirs:
                        target_path = Path(root) / d
                        if target_path.is_dir() and not self.linker.is_link(target_path):
                            total_directories += 1
                            dir_hash = self._generate_content_hash(target_path)

                            if dir_hash not in hash_to_paths:
                                hash_to_paths[dir_hash] = []
                                hash_to_size[dir_hash] = self._get_dir_size(target_path)

                            hash_to_paths[dir_hash].append(target_path)

        groups = []
        total_waste_bytes = 0

        for h, paths in hash_to_paths.items():
            if len(paths) > 1:
                # Sibling workspace packages belong to one logical project;
                # only flag duplicate candidate groups spanning multiple distinct projects
                logical_projects = {_get_logical_project_root(p) for p in paths}
                if len(logical_projects) > 1:
                    size = hash_to_size[h]
                    savings = size * (len(paths) - 1)
                    total_waste_bytes += savings
                    groups.append(DuplicateGroup(h, paths, size, savings))

        # Sort groups by potential savings
        groups.sort(key=lambda g: g.potential_savings, reverse=True)

        return DuplicateReport(groups, total_waste_bytes, total_directories)

    def get_status(self) -> Dict[str, Any]:
        """Get the current status and savings report of the deduplication engine."""
        return self.registry.get_savings_report()
