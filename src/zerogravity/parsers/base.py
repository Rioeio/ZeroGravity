"""
Unified data models for the Manifest Parser engine.

Defines the canonical representations for project dependencies, manifests,
and the abstract parser interface that all ecosystem-specific parsers implement.
"""

from __future__ import annotations

import enum
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


class DependencyType(enum.Enum):
    """Classification of a dependency's role in the project."""
    PRODUCTION = "production"
    DEVELOPMENT = "development"
    PEER = "peer"
    OPTIONAL = "optional"
    BUILD = "build"


class Ecosystem(enum.Enum):
    """Supported package ecosystems."""
    NODE = "node"
    PYTHON = "python"
    GO = "go"
    RUBY = "ruby"
    RUST = "rust"
    UNKNOWN = "unknown"


@dataclass
class Dependency:
    """
    Represents a single project dependency with its version specification
    and resolution state.

    Attributes:
        name: Package name (e.g., "express", "requests").
        version_spec: Declared version constraint (e.g., "^4.18.0", ">=3.0,<4.0").
        resolved_version: Exact resolved version from lockfile, if available.
        dep_type: Role of this dependency (production, dev, peer, optional, build).
        extras: Optional extras / features requested (e.g., Python's `requests[security]`).
        source: Where this dependency was declared (e.g., "package.json", "requirements.txt").
        metadata: Any additional ecosystem-specific metadata.
    """
    name: str
    version_spec: str = ""
    resolved_version: str | None = None
    dep_type: DependencyType = DependencyType.PRODUCTION
    extras: list[str] = field(default_factory=list)
    source: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def __str__(self) -> str:
        version = self.resolved_version or self.version_spec or "any"
        return f"{self.name}@{version} ({self.dep_type.value})"


@dataclass
class ProjectManifest:
    """
    Unified representation of a project's dependency declarations,
    normalised from any ecosystem-specific manifest format.

    This is the canonical data structure that flows from parsers into
    the Resolution Engine for conflict detection.

    Attributes:
        project_path: Absolute path to the project root directory.
        project_name: Human-readable project name (from manifest metadata).
        ecosystem: Which package ecosystem this manifest belongs to.
        dependencies: All declared dependencies, normalised.
        engine_constraints: Runtime version constraints declared by the project
            (e.g., {"node": ">=18.0.0", "npm": ">=9.0.0"}).
        lockfile_present: Whether a lockfile was found alongside the manifest.
        lockfile_path: Path to the lockfile, if found.
        manifest_files: List of manifest files that were parsed.
        metadata: Raw ecosystem-specific metadata not captured above.
    """
    project_path: Path
    project_name: str = ""
    ecosystem: Ecosystem = Ecosystem.UNKNOWN
    dependencies: list[Dependency] = field(default_factory=list)
    engine_constraints: dict[str, str] = field(default_factory=dict)
    lockfile_present: bool = False
    lockfile_path: Path | None = None
    manifest_files: list[Path] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def production_deps(self) -> list[Dependency]:
        """Return only production dependencies."""
        return [d for d in self.dependencies if d.dep_type == DependencyType.PRODUCTION]

    @property
    def dev_deps(self) -> list[Dependency]:
        """Return only development dependencies."""
        return [d for d in self.dependencies if d.dep_type == DependencyType.DEVELOPMENT]

    @property
    def peer_deps(self) -> list[Dependency]:
        """Return only peer dependencies."""
        return [d for d in self.dependencies if d.dep_type == DependencyType.PEER]

    @property
    def total_count(self) -> int:
        """Total number of declared dependencies."""
        return len(self.dependencies)

    def __str__(self) -> str:
        return (
            f"ProjectManifest({self.project_name or self.project_path.name}, "
            f"ecosystem={self.ecosystem.value}, deps={self.total_count})"
        )


class BaseParser(ABC):
    """
    Abstract interface for ecosystem-specific manifest parsers.

    Every parser must implement two methods:
    - can_parse(): Detects whether this parser applies to a given directory.
    - parse(): Reads manifest files and returns a normalised ProjectManifest.
    """

    @property
    @abstractmethod
    def ecosystem(self) -> Ecosystem:
        """The ecosystem this parser handles."""
        ...

    @abstractmethod
    def can_parse(self, project_path: Path) -> bool:
        """
        Check if this parser can handle the project at the given path.

        Args:
            project_path: Path to the project root directory.

        Returns:
            True if this parser's manifest files are present.
        """
        ...

    @abstractmethod
    def parse(self, project_path: Path) -> ProjectManifest:
        """
        Parse the project at the given path and return a normalised manifest.

        Args:
            project_path: Path to the project root directory.

        Returns:
            A ProjectManifest with all dependencies extracted and normalised.

        Raises:
            FileNotFoundError: If expected manifest files are missing.
            ValueError: If manifest files contain malformed data.
        """
        ...
