"""
Configuration loader and starter template generator for ZeroGravity (.zerogravity.toml).
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

CONFIG_FILENAME = ".zerogravity.toml"

STARTER_CONFIG_TEMPLATE = """# .zerogravity.toml — ZeroGravity Project Configuration

[scan]
# Additional directory names or glob patterns to exclude from recursive scanning
# (extends built-in exclusions like node_modules, .venv, dist, etc.)
exclude = [
    # "tmp",
    # "build_cache",
    # "legacy_*",
]

[binary_map]
# Custom mappings from package name to required system binaries
# Overrides or augments built-in system dependency rules
# Example:
# "my-pkg" = ["custom_bin"]
# "cryptography" = ["openssl"]

[ignore]
# Issue categories to ignore in conflict reports:
# Options: "lockfile_missing", "missing_system_dep", "cross_project_conflict",
#          "engine_constraint_violation", "missing_binary"
issues = [
    # "lockfile_missing",
]

# Package names to ignore during system dependency and conflict checks
packages = [
    # "some-optional-dep",
]
"""


@dataclass
class ZeroGravityConfig:
    """
    Project-level configuration loaded from .zerogravity.toml.

    Attributes:
        exclude: List of directory names or glob patterns to exclude during recursive scan.
        binary_map: Custom mapping of package name to required system binaries.
        ignore_issues: List of issue category strings or identifiers to ignore.
        ignore_packages: List of package names to ignore in reports and checks.
        config_path: Path to the loaded configuration file, if any.
    """
    exclude: list[str] = field(default_factory=list)
    binary_map: dict[str, list[str]] = field(default_factory=dict)
    ignore_issues: list[str] = field(default_factory=list)
    ignore_packages: list[str] = field(default_factory=list)
    config_path: Path | None = None


def find_config_file(start_path: Path | None = None) -> Path | None:
    """
    Locate .zerogravity.toml in start_path or any of its parent directories.
    """
    current = (start_path or Path.cwd()).resolve()
    if current.is_file():
        current = current.parent

    while current != current.parent:
        candidate = current / CONFIG_FILENAME
        if candidate.is_file():
            return candidate
        if (current / ".git").is_dir():
            break
        current = current.parent

    # Also check the root directory where loop stopped
    root_candidate = current / CONFIG_FILENAME
    if root_candidate.is_file():
        return root_candidate

    return None


def parse_config_data(data: dict[str, Any], config_path: Path | None = None) -> ZeroGravityConfig:
    """
    Parse a raw dictionary from .zerogravity.toml into a ZeroGravityConfig object.
    """
    exclude: list[str] = []
    binary_map: dict[str, list[str]] = {}
    ignore_issues: list[str] = []
    ignore_packages: list[str] = []

    # 1. Scan section
    scan_section = data.get("scan", {})
    if isinstance(scan_section, dict):
        raw_exclude = scan_section.get("exclude", [])
        if isinstance(raw_exclude, list):
            exclude = [str(x).strip() for x in raw_exclude if str(x).strip()]

    # 2. Binary map section (supports [binary_map], [binary-map], [binaries])
    raw_bmap = data.get("binary_map") or data.get("binary-map") or data.get("binaries") or {}
    if isinstance(raw_bmap, dict):
        for pkg, bins in raw_bmap.items():
            pkg_clean = str(pkg).strip().lower()
            if isinstance(bins, list):
                binary_map[pkg_clean] = [str(b).strip() for b in bins if str(b).strip()]
            elif isinstance(bins, str):
                binary_map[pkg_clean] = [bins.strip()]

    # 3. Ignore section
    ignore_section = data.get("ignore", {})
    if isinstance(ignore_section, dict):
        raw_issues = ignore_section.get("issues") or ignore_section.get("categories") or []
        if isinstance(raw_issues, list):
            ignore_issues = [str(x).strip().lower() for x in raw_issues if str(x).strip()]
        elif isinstance(raw_issues, str):
            ignore_issues = [raw_issues.strip().lower()]

        raw_pkgs = ignore_section.get("packages") or []
        if isinstance(raw_pkgs, list):
            ignore_packages = [str(x).strip().lower() for x in raw_pkgs if str(x).strip()]
        elif isinstance(raw_pkgs, str):
            ignore_packages = [raw_pkgs.strip().lower()]
    elif isinstance(ignore_section, list):
        # Support flat ignore = ["lockfile_missing", "pkg_name"]
        for item in ignore_section:
            clean_item = str(item).strip().lower()
            if clean_item:
                ignore_issues.append(clean_item)
                ignore_packages.append(clean_item)

    return ZeroGravityConfig(
        exclude=exclude,
        binary_map=binary_map,
        ignore_issues=ignore_issues,
        ignore_packages=ignore_packages,
        config_path=config_path,
    )


def load_config(path: Path | None = None) -> ZeroGravityConfig:
    """
    Load .zerogravity.toml from given path, file path, or search ancestor directories.
    If no config file is found or parsing fails, returns default configuration.
    """
    config_file: Path | None = None

    if path is not None:
        p = Path(path).resolve()
        if p.is_file() and p.name == CONFIG_FILENAME:
            config_file = p
        elif p.is_dir() and (p / CONFIG_FILENAME).is_file():
            config_file = p / CONFIG_FILENAME
        else:
            config_file = find_config_file(p)
    else:
        config_file = find_config_file()

    if config_file is None or not config_file.is_file():
        return ZeroGravityConfig()

    try:
        with open(config_file, "rb") as f:
            data = tomllib.load(f)
        return parse_config_data(data, config_path=config_file)
    except Exception:
        return ZeroGravityConfig(config_path=config_file)


def create_starter_config(target_dir: Path, force: bool = False) -> Path:
    """
    Scaffold a starter .zerogravity.toml in the target directory.

    Raises:
        FileExistsError: If config file already exists and force is False.
    """
    target_dir = target_dir.resolve()
    target_file = target_dir / CONFIG_FILENAME

    if target_file.exists() and not force:
        raise FileExistsError(
            f"Configuration file already exists at {target_file}. Use --force to overwrite."
        )

    target_dir.mkdir(parents=True, exist_ok=True)
    target_file.write_text(STARTER_CONFIG_TEMPLATE, encoding="utf-8")
    return target_file
