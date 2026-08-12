from __future__ import annotations

import os
import shutil
import hashlib
from pathlib import Path
from dataclasses import dataclass
from typing import List, Dict, Optional, Any

from zerogravity.dedup.linker import CrossPlatformLinker, LinkResult
from zerogravity.dedup.registry import DeduplicationRegistry

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
                except Exception:
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
                    
                shutil.rmtree(temp_path, ignore_errors=True)
                bytes_saved = dir_size
                
            else:
                # Move to store and create link
                shutil.move(str(dep_path), str(store_package_path))
                
                # Make store files read-only
                for root, _, files in os.walk(store_package_path):
                    for file in files:
                        os.chmod(os.path.join(root, file), 0o444)
                
                link_result = self.linker.create_link(store_package_path, dep_path)
                if link_result.status == "error":
                    # Rollback
                    shutil.move(str(store_package_path), str(dep_path))
                    return OptimizationResult("error", dir_hash, 0, None, None, link_result.error_message)
                    
                self.registry.register_package(dir_hash, str(store_package_path), dir_size, file_count)
                bytes_saved = 0 # No space saved on first ingestion
                
            self.registry.register_link(dir_hash, str(dep_path), str(dep_path.parent), str(dep_path))
            
            return OptimizationResult("success", dir_hash, bytes_saved, dep_path, store_package_path)
            
        except Exception as e:
            return OptimizationResult("error", dir_hash, 0, None, None, str(e))

    def restore(self, dep_path: Path) -> RestoreResult:
        """Restore a linked dependency back to a physical copy."""
        dep_path = dep_path.absolute()
        
        if not self.linker.is_link(dep_path):
            return RestoreResult("error", dep_path, "Path is not a managed link")
            
        target_path = self.linker.resolve_link(dep_path)
        if not target_path or not target_path.exists():
            return RestoreResult("error", dep_path, "Link target does not exist")
            
        try:
            self.linker.remove_link(dep_path)
            shutil.copytree(target_path, dep_path)
            # Restore write permissions
            for root, _, files in os.walk(dep_path):
                for file in files:
                    os.chmod(os.path.join(root, file), 0o644)
            self.registry.remove_link(str(dep_path))
            return RestoreResult("success", dep_path)
        except Exception as e:
            return RestoreResult("error", dep_path, str(e))

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
