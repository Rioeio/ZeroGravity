"""
Scan-result cache manager keyed by (manifest path, content hash, mtime).
Stored alongside ~/.zerogravity/scan_history.json.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from zerogravity.parsers.base import (
    Dependency,
    DependencyType,
    Ecosystem,
    ProjectManifest,
)

CACHE_FILENAME = "scan_cache.json"

MANIFEST_AND_LOCK_FILENAMES = [
    "package.json",
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    "pnpm-workspace.yaml",
    "pyproject.toml",
    "requirements.txt",
    "poetry.lock",
    "Pipfile",
    "Pipfile.lock",
    ".zerogravity.toml",
    "Dockerfile",
    "Containerfile",
    ".devcontainer.json",
    "docker-compose.yml",
    "docker-compose.yaml",
    "compose.yaml",
]


def _compute_file_hash(path: Path) -> str:
    """Compute SHA-256 hash of a file."""
    hasher = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            while chunk := f.read(65536):
                hasher.update(chunk)
        return hasher.hexdigest()
    except OSError:
        return ""


def _get_file_stat(path: Path) -> dict[str, Any]:
    """Retrieve file mtime, size, and content hash."""
    try:
        stat = path.stat()
        return {
            "mtime": stat.st_mtime,
            "size": stat.st_size,
            "hash": _compute_file_hash(path),
        }
    except OSError:
        return {}


def manifest_to_dict(manifest: ProjectManifest) -> dict[str, Any]:
    """Serialize a ProjectManifest to a JSON-compatible dictionary."""
    return {
        "project_path": str(manifest.project_path),
        "project_name": manifest.project_name,
        "ecosystem": manifest.ecosystem.value,
        "dependencies": [
            {
                "name": d.name,
                "version_spec": d.version_spec,
                "resolved_version": d.resolved_version,
                "dep_type": d.dep_type.value,
                "extras": d.extras,
                "source": d.source,
                "metadata": d.metadata,
            }
            for d in manifest.dependencies
        ],
        "engine_constraints": manifest.engine_constraints,
        "lockfile_present": manifest.lockfile_present,
        "lockfile_path": str(manifest.lockfile_path) if manifest.lockfile_path else None,
        "manifest_files": [str(m) for m in manifest.manifest_files],
        "metadata": manifest.metadata,
        "workspace_root": str(manifest.workspace_root) if manifest.workspace_root else None,
        "workspace_members": [str(m) for m in manifest.workspace_members],
        "is_workspace_root": manifest.is_workspace_root,
        "is_workspace_member": manifest.is_workspace_member,
        "container_file": str(manifest.container_file) if manifest.container_file else None,
    }


def dict_to_manifest(data: dict[str, Any]) -> ProjectManifest:
    """Deserialize a dictionary to a ProjectManifest object."""
    deps = [
        Dependency(
            name=d["name"],
            version_spec=d.get("version_spec", ""),
            resolved_version=d.get("resolved_version"),
            dep_type=DependencyType(d.get("dep_type", DependencyType.PRODUCTION.value)),
            extras=d.get("extras", []),
            source=d.get("source", ""),
            metadata=d.get("metadata", {}),
        )
        for d in data.get("dependencies", [])
    ]
    return ProjectManifest(
        project_path=Path(data["project_path"]),
        project_name=data.get("project_name", ""),
        ecosystem=Ecosystem(data.get("ecosystem", Ecosystem.UNKNOWN.value)),
        dependencies=deps,
        engine_constraints=data.get("engine_constraints", {}),
        lockfile_present=data.get("lockfile_present", False),
        lockfile_path=Path(data["lockfile_path"]) if data.get("lockfile_path") else None,
        manifest_files=[Path(m) for m in data.get("manifest_files", [])],
        metadata=data.get("metadata", {}),
        workspace_root=Path(data["workspace_root"]) if data.get("workspace_root") else None,
        workspace_members=[Path(m) for m in data.get("workspace_members", [])],
        is_workspace_root=data.get("is_workspace_root", False),
        is_workspace_member=data.get("is_workspace_member", False),
        container_file=Path(data["container_file"]) if data.get("container_file") else None,
    )


class ScanCacheManager:
    """
    Manages caching of parsed project manifests keyed by file mtimes and hashes.
    """

    def __init__(self, cache_file: Path | None = None) -> None:
        if cache_file is not None:
            self.cache_file = Path(cache_file)
            self.cache_dir = self.cache_file.parent
        else:
            self.cache_dir = Path.home() / ".zerogravity"
            self.cache_file = self.cache_dir / CACHE_FILENAME

    def _ensure_dir(self) -> None:
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _load_raw_cache(self) -> dict[str, Any]:
        if not self.cache_file.exists():
            return {}
        try:
            with open(self.cache_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return {}

    def _save_raw_cache(self, data: dict[str, Any]) -> None:
        self._ensure_dir()
        try:
            with open(self.cache_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except OSError:
            pass

    def get_project_files_stat(self, project_path: Path) -> dict[str, dict[str, Any]]:
        """Collect mtime, size, and hash for all manifest/lockfile files in project."""
        stats: dict[str, dict[str, Any]] = {}
        for filename in MANIFEST_AND_LOCK_FILENAMES:
            fp = project_path / filename
            if fp.is_file():
                stats[str(fp.resolve())] = _get_file_stat(fp)
        return stats

    def get(self, project_path: Path) -> list[ProjectManifest] | None:
        """
        Retrieve cached manifests if all relevant files in project_path have matching mtime and hash.
        """
        project_path = project_path.resolve()
        cache_data = self._load_raw_cache()
        key = str(project_path)

        if key not in cache_data:
            return None

        entry = cache_data[key]
        cached_files_stat: dict[str, dict[str, Any]] = entry.get("files_stat", {})

        current_files = [project_path / f for f in MANIFEST_AND_LOCK_FILENAMES if (project_path / f).is_file()]
        if len(current_files) != len(cached_files_stat):
            return None

        for fp in current_files:
            resolved_str = str(fp.resolve())
            if resolved_str not in cached_files_stat:
                return None

            expected_stat = cached_files_stat[resolved_str]
            try:
                current_stat = fp.stat()
            except OSError:
                return None

            # Fast check: mtime and size
            if current_stat.st_mtime != expected_stat.get("mtime") or current_stat.st_size != expected_stat.get("size"):
                return None

            # Deep check: hash
            current_hash = _compute_file_hash(fp)
            if current_hash != expected_stat.get("hash"):
                return None

        manifests_raw = entry.get("manifests", [])
        return [dict_to_manifest(m) for m in manifests_raw]

    def set(self, project_path: Path, manifests: list[ProjectManifest]) -> None:
        """
        Store manifests in cache along with the current file stats of project_path.
        """
        project_path = project_path.resolve()
        cache_data = self._load_raw_cache()
        key = str(project_path)

        files_stat = self.get_project_files_stat(project_path)
        cache_data[key] = {
            "project_path": key,
            "files_stat": files_stat,
            "manifests": [manifest_to_dict(m) for m in manifests],
        }

        self._save_raw_cache(cache_data)

    def clear(self) -> None:
        """Clear all cached scan results."""
        if self.cache_file.exists():
            try:
                self.cache_file.unlink()
            except OSError:
                pass
