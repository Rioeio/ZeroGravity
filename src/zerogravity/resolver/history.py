from __future__ import annotations

import logging
from datetime import timedelta
from pathlib import Path
from typing import Any

from zerogravity.parsers.base import Ecosystem, ProjectManifest
from zerogravity.state import (
    atomic_write_json,
    ensure_state_dir,
    file_lock,
    get_lock_path,
    get_state_dir,
    load_json,
)
from zerogravity.time import parse_utc_iso, to_utc_iso, utc_now

logger = logging.getLogger(__name__)


class ScanHistoryManager:
    """Manages persistence and retrieval of project scan history."""

    def __init__(self, history_dir: Path | None = None, max_entries: int | None = None) -> None:
        if history_dir is not None:
            self.history_dir = Path(history_dir)
        else:
            self.history_dir = get_state_dir()
        self.history_file = self.history_dir / "scan_history.json"
        self.lock_file = get_lock_path(self.history_file)

        if max_entries is not None:
            self.max_entries = max_entries
        else:
            try:
                from zerogravity.config import ConfigError, load_config
                self.max_entries = load_config().history_max_entries
            except (ConfigError, OSError, ValueError):
                self.max_entries = 1000

    def _ensure_dir(self) -> None:
        ensure_state_dir(self.history_dir)

    def save_manifests(self, manifests: list[ProjectManifest]) -> None:
        """Stores serialized manifest info with lock and bounded capacity."""
        self._ensure_dir()
        with file_lock(self.lock_file):
            current_history: dict[str, Any] = load_json(self.history_file, default={})
            if not isinstance(current_history, dict):
                current_history = {}

            now_str = to_utc_iso()
            for manifest in manifests:
                path_str = str(manifest.project_path)
                eco_val = manifest.ecosystem.value if hasattr(manifest.ecosystem, "value") else (str(manifest.ecosystem) if manifest.ecosystem else Ecosystem.UNKNOWN.value)
                current_history[path_str] = {
                    "project_path": path_str,
                    "project_name": manifest.project_name,
                    "ecosystem": eco_val,
                    "engine_constraints": manifest.engine_constraints,
                    "dependencies_summary": len(manifest.dependencies),
                    "timestamp": now_str,
                }

            if len(current_history) > self.max_entries:
                def _ts_key(item: tuple[str, Any]) -> float:
                    if isinstance(item[1], dict) and "timestamp" in item[1]:
                        try:
                            return parse_utc_iso(item[1]["timestamp"]).timestamp()
                        except (ValueError, TypeError):
                            return 0.0
                    return 0.0

                sorted_items = sorted(current_history.items(), key=_ts_key)
                current_history = dict(sorted_items[-self.max_entries:])

            atomic_write_json(self.history_file, current_history)

    def load_recent_manifests(self, max_age_days: int = 30) -> list[ProjectManifest]:
        """Loads active historical project manifests from disk."""
        if not self.history_file.exists():
            return []

        history_data = load_json(self.history_file, default={})
        if not isinstance(history_data, dict):
            return []

        cutoff = utc_now() - timedelta(days=max_age_days)
        manifests = []

        for path_str, data in history_data.items():
            if not isinstance(data, dict):
                continue
            project_path = Path(path_str)
            if not project_path.exists() or not project_path.is_dir():
                continue

            timestamp_str = data.get("timestamp")
            if not timestamp_str:
                continue

            try:
                timestamp = parse_utc_iso(timestamp_str)
            except (ValueError, TypeError):
                continue

            if timestamp < cutoff:
                continue

            eco_raw = data.get("ecosystem", Ecosystem.UNKNOWN.value)
            try:
                eco_parsed = Ecosystem(eco_raw)
            except ValueError:
                eco_parsed = Ecosystem.UNKNOWN

            manifest = ProjectManifest(
                project_path=project_path,
                project_name=data.get("project_name", ""),
                ecosystem=eco_parsed,
                dependencies=[],
                engine_constraints=data.get("engine_constraints", {}),
                lockfile_present=False,
                lockfile_path=None,
                manifest_files=[],
                metadata={},
            )
            manifests.append(manifest)

        return manifests

    def get_history_entries(self) -> dict[str, dict[str, Any]]:
        """Return all scan history entries."""
        if not self.history_file.exists():
            return {}
        data = load_json(self.history_file, default={})
        return data if isinstance(data, dict) else {}

    def get_history(self) -> dict[str, dict[str, Any]]:
        """Alias for get_history_entries."""
        return self.get_history_entries()

    def get_recent_scans(self, max_age_days: int = 30) -> list[ProjectManifest]:
        """Alias for load_recent_manifests."""
        return self.load_recent_manifests(max_age_days=max_age_days)

    def clear_history(self, path: Path | str | None = None) -> None:
        """Resets history file or removes a single project entry."""
        if not self.history_file.exists():
            return

        self._ensure_dir()
        with file_lock(self.lock_file):
            if path is None:
                try:
                    self.history_file.unlink()
                except OSError:
                    pass
                return

            target_path_str = str(Path(path).resolve())
            data = load_json(self.history_file, default={})
            if isinstance(data, dict):
                keys_to_remove = [
                    k for k in data
                    if str(Path(k).resolve()) == target_path_str or k == str(path)
                ]
                for k in keys_to_remove:
                    del data[k]
                atomic_write_json(self.history_file, data)
