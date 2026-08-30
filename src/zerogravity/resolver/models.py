"""
Data models for the Resolution Engine.

Defines severity levels, issue categories, and the ResolutionReport
structure that flows from conflict detection into the UI renderer.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


class Severity(enum.Enum):
    """Severity classification for detected issues."""
    OK = "ok"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"

    @property
    def priority(self) -> int:
        """Numeric priority for sorting (higher = more severe)."""
        return {
            Severity.OK: 0,
            Severity.INFO: 1,
            Severity.WARNING: 2,
            Severity.ERROR: 3,
            Severity.CRITICAL: 4,
        }[self]

    @property
    def color(self) -> str:
        """Rich markup color for this severity level."""
        return {
            Severity.OK: "green",
            Severity.INFO: "cyan",
            Severity.WARNING: "yellow",
            Severity.ERROR: "red",
            Severity.CRITICAL: "bold red",
        }[self]

    @property
    def icon(self) -> str:
        """Status icon for terminal display."""
        return {
            Severity.OK: "[OK]",
            Severity.INFO: "[INFO]",
            Severity.WARNING: "[WARN]",
            Severity.ERROR: "[ERROR]",
            Severity.CRITICAL: "[CRIT]",
        }[self]


class IssueCategory(enum.Enum):
    """Classification of what kind of issue was detected."""
    VERSION_MISMATCH = "version_mismatch"
    MISSING_BINARY = "missing_binary"
    MISSING_SYSTEM_DEP = "missing_system_dep"
    CROSS_PROJECT_CONFLICT = "cross_project_conflict"
    LOCKFILE_MISSING = "lockfile_missing"
    ENGINE_CONSTRAINT_VIOLATION = "engine_constraint_violation"
    DEPRECATED_VERSION = "deprecated_version"
    CONTAINER_RESOLVED = "container_resolved"


@dataclass
class Issue:
    """
    A single detected issue from the Resolution Engine.

    Attributes:
        severity: How critical this issue is.
        category: What kind of issue this is.
        message: Human-readable description of the problem.
        source_project: Path or name of the project that triggered this issue.
        affected_binary: The binary or dependency name involved.
        expected: What the project expects (version spec or binary name).
        actual: What was actually found on the system.
        remediation: Suggested fix command or action, if available.
        metadata: Additional context for the issue.
    """
    severity: Severity
    category: IssueCategory
    message: str
    source_project: str = ""
    affected_binary: str = ""
    expected: str = ""
    actual: str = ""
    remediation: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __str__(self) -> str:
        return f"[{self.severity.value.upper()}] {self.message}"


@dataclass
class ResolutionReport:
    """
    Aggregated output of a conflict detection run.

    Contains all issues found, sorted by severity, with summary statistics
    for quick dashboard rendering.

    Attributes:
        issues: All detected issues.
        scanned_projects: Number of projects that were scanned.
        scanned_binaries: Number of system binaries that were probed.
        timestamp: When this report was generated.
    """
    issues: list[Issue] = field(default_factory=list)
    scanned_projects: int = 0
    scanned_binaries: int = 0
    timestamp: datetime = field(default_factory=datetime.now)

    @property
    def critical_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == Severity.CRITICAL)

    @property
    def error_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == Severity.ERROR)

    @property
    def warning_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == Severity.WARNING)

    @property
    def ok_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == Severity.OK)

    @property
    def has_critical_issues(self) -> bool:
        return self.critical_count > 0

    @property
    def has_errors(self) -> bool:
        return self.error_count > 0

    @property
    def sorted_issues(self) -> list[Issue]:
        """Issues sorted by severity (most critical first)."""
        return sorted(self.issues, key=lambda i: i.severity.priority, reverse=True)

    @property
    def summary(self) -> dict[str, int]:
        """Summary counts by severity level."""
        return {
            "critical": self.critical_count,
            "errors": self.error_count,
            "warnings": self.warning_count,
            "ok": self.ok_count,
            "total": len(self.issues),
        }


@dataclass
class BinaryProbe:
    """
    Result of probing a single system binary.

    Attributes:
        name: Binary identifier (e.g., "node", "python3", "docker").
        installed: Whether the binary was found in PATH.
        path: Absolute path to the binary, if found.
        version: Extracted semantic version string.
        error: Error message if probing failed.
    """
    name: str
    installed: bool = False
    path: str | None = None
    version: str | None = None
    error: str | None = None

    @property
    def is_healthy(self) -> bool:
        return self.installed and self.version is not None and self.error is None


@dataclass
class SystemSnapshot:
    """
    Complete snapshot of the local OS state at a point in time.

    Aggregates all probed binaries, environment variables, detected
    version managers, and platform information.

    Attributes:
        binaries: Map of binary name to probe results.
        env_vars: Relevant environment variable values.
        version_managers: Detected version manager state.
        platform: OS and architecture info.
        timestamp: When this snapshot was captured.
    """
    binaries: dict[str, BinaryProbe] = field(default_factory=dict)
    env_vars: dict[str, str] = field(default_factory=dict)
    version_managers: dict[str, VersionManagerInfo] = field(default_factory=dict)
    platform: dict[str, str] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.now)

    def get_binary(self, name: str) -> BinaryProbe | None:
        """Get probe result for a specific binary."""
        return self.binaries.get(name)

    def get_version(self, binary_name: str) -> str | None:
        """Get the version of a specific binary, or None if not found."""
        probe = self.binaries.get(binary_name)
        return probe.version if probe and probe.installed else None


@dataclass
class VersionManagerInfo:
    """
    State of a detected version manager.

    Attributes:
        name: Manager identifier (e.g., "nvm", "pyenv", "asdf").
        detected: Whether this manager was found on the system.
        root_path: Installation root directory.
        active_version: Currently active version managed by this tool.
        installed_versions: All versions installed via this manager.
    """
    name: str
    detected: bool = False
    root_path: str | None = None
    active_version: str | None = None
    installed_versions: list[str] = field(default_factory=list)
