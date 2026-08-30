"""
Data models for outdated dependency detection.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from pathlib import Path

from zerogravity.parsers.base import Ecosystem


class UpdateType(enum.Enum):
    """Classification of version difference."""
    MAJOR = "major"
    MINOR = "minor"
    PATCH = "patch"
    UP_TO_DATE = "up_to_date"
    UNKNOWN = "unknown"

    @property
    def color(self) -> str:
        return {
            UpdateType.MAJOR: "bold red",
            UpdateType.MINOR: "yellow",
            UpdateType.PATCH: "cyan",
            UpdateType.UP_TO_DATE: "green",
            UpdateType.UNKNOWN: "dim",
        }[self]


@dataclass
class OutdatedPackage:
    """Represents an analyzed dependency compared against registry latest."""
    name: str
    current_version: str
    latest_version: str
    update_type: UpdateType
    ecosystem: Ecosystem
    project_path: Path
    project_name: str = ""
    source: str = ""


@dataclass
class OutdatedReport:
    """Aggregated outdated analysis for all scanned projects."""
    packages: list[OutdatedPackage] = field(default_factory=list)
    scanned_dependencies: int = 0

    @property
    def major_count(self) -> int:
        return sum(1 for p in self.packages if p.update_type == UpdateType.MAJOR)

    @property
    def minor_count(self) -> int:
        return sum(1 for p in self.packages if p.update_type == UpdateType.MINOR)

    @property
    def patch_count(self) -> int:
        return sum(1 for p in self.packages if p.update_type == UpdateType.PATCH)

    @property
    def total_outdated(self) -> int:
        return self.major_count + self.minor_count + self.patch_count

    @property
    def summary(self) -> dict[str, int]:
        return {
            "major": self.major_count,
            "minor": self.minor_count,
            "patch": self.patch_count,
            "total_outdated": self.total_outdated,
            "total_scanned": self.scanned_dependencies,
        }
