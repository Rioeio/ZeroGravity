"""
Data models for OSV.dev vulnerability advisories and security auditing.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from pathlib import Path

from zerogravity.parsers.base import Ecosystem


class VulnerabilitySeverity(enum.Enum):
    """Vulnerability severity classification."""
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    UNKNOWN = "UNKNOWN"

    @property
    def color(self) -> str:
        return {
            VulnerabilitySeverity.CRITICAL: "bold white on red",
            VulnerabilitySeverity.HIGH: "bold red",
            VulnerabilitySeverity.MEDIUM: "yellow",
            VulnerabilitySeverity.LOW: "cyan",
            VulnerabilitySeverity.UNKNOWN: "dim",
        }[self]

    @property
    def priority(self) -> int:
        return {
            VulnerabilitySeverity.CRITICAL: 4,
            VulnerabilitySeverity.HIGH: 3,
            VulnerabilitySeverity.MEDIUM: 2,
            VulnerabilitySeverity.LOW: 1,
            VulnerabilitySeverity.UNKNOWN: 0,
        }[self]


@dataclass
class VulnerabilityAdvisory:
    """Represents a security vulnerability advisory from OSV.dev."""
    id: str  # GHSA-xxx, OSV-xxx, PYSEC-xxx
    cve_id: str | None
    package_name: str
    installed_version: str
    ecosystem: Ecosystem
    summary: str
    details: str
    severity: VulnerabilitySeverity
    cvss_score: str | None = None
    project_path: Path = field(default_factory=Path.cwd)
    project_name: str = ""


@dataclass
class SecurityReport:
    """Aggregated vulnerability findings across scanned project manifests."""
    advisories: list[VulnerabilityAdvisory] = field(default_factory=list)
    scanned_packages: int = 0

    @property
    def critical_count(self) -> int:
        return sum(1 for a in self.advisories if a.severity == VulnerabilitySeverity.CRITICAL)

    @property
    def high_count(self) -> int:
        return sum(1 for a in self.advisories if a.severity == VulnerabilitySeverity.HIGH)

    @property
    def medium_count(self) -> int:
        return sum(1 for a in self.advisories if a.severity == VulnerabilitySeverity.MEDIUM)

    @property
    def low_count(self) -> int:
        return sum(1 for a in self.advisories if a.severity == VulnerabilitySeverity.LOW)

    @property
    def total_vulnerabilities(self) -> int:
        return len(self.advisories)

    @property
    def summary(self) -> dict[str, int]:
        return {
            "critical": self.critical_count,
            "high": self.high_count,
            "medium": self.medium_count,
            "low": self.low_count,
            "total_vulnerabilities": self.total_vulnerabilities,
            "total_scanned": self.scanned_packages,
        }
