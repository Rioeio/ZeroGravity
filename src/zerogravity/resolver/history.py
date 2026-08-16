from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path

from zerogravity.parsers.base import Ecosystem, ProjectManifest

logger = logging.getLogger(__name__)

class ScanHistoryManager:
    """Manages the persistence and retrieval of project scan history."""

    def __init__(self) -> None:
        self.history_dir = Path.home() / ".zerogravity"
        self.history_file = self.history_dir / "scan_history.json"

    def _ensure_dir(self) -> None:
        self.history_dir.mkdir(parents=True, exist_ok=True)

    def save_manifests(self, manifests: list[ProjectManifest]) -> None:
        """Stores serialized manifest info."""
        self._ensure_dir()

        current_history = {}
        if self.history_file.exists():
            try:
                with open(self.history_file, "r", encoding="utf-8") as f:
                    current_history = json.load(f)
            except json.JSONDecodeError:
                pass

        now_str = datetime.now().isoformat()
        for manifest in manifests:
            path_str = str(manifest.project_path)
            current_history[path_str] = {
                "project_path": path_str,
                "project_name": manifest.project_name,
                "ecosystem": manifest.ecosystem.value if manifest.ecosystem else Ecosystem.UNKNOWN.value,
                "engine_constraints": manifest.engine_constraints,
                "dependencies_summary": len(manifest.dependencies),
                "timestamp": now_str
            }

        with open(self.history_file, "w", encoding="utf-8") as f:
            json.dump(current_history, f, indent=2)

    def load_recent_manifests(self, max_age_days: int = 30) -> list[ProjectManifest]:
        """Loads active historical project manifests from disk."""
        if not self.history_file.exists():
            return []

        try:
            with open(self.history_file, "r", encoding="utf-8") as f:
                history_data = json.load(f)
        except json.JSONDecodeError:
            return []

        cutoff = datetime.now() - timedelta(days=max_age_days)
        manifests = []

        for path_str, data in history_data.items():
            project_path = Path(path_str)
            if not project_path.exists() or not project_path.is_dir():
                continue

            timestamp_str = data.get("timestamp")
            if not timestamp_str:
                continue

            try:
                timestamp = datetime.fromisoformat(timestamp_str)
            except ValueError:
                continue

            if timestamp < cutoff:
                continue

            manifest = ProjectManifest(
                project_path=project_path,
                project_name=data.get("project_name", ""),
                ecosystem=Ecosystem(data.get("ecosystem", Ecosystem.UNKNOWN.value)),
                dependencies=[],  # We don't store full deps in history
                engine_constraints=data.get("engine_constraints", {}),
                lockfile_present=False,
                lockfile_path=None,
                manifest_files=[],
                metadata={}
            )
            manifests.append(manifest)

        return manifests

    def clear_history(self) -> None:
        """Resets history file."""
        if self.history_file.exists():
            self.history_file.unlink()
