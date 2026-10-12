"""
Configuration loader and starter template generator for ZeroGravity (.zerogravity.toml).
"""

from __future__ import annotations

import difflib
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

CONFIG_FILENAME = ".zerogravity.toml"


class ConfigError(Exception):
    """Raised when a configuration file is malformed or contains invalid types."""

    def __init__(
        self,
        message: str,
        file: Path | None = None,
        line: int | None = None,
        col: int | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.file = file
        self.line = line
        self.col = col

    def __str__(self) -> str:
        loc_parts: list[str] = []
        if self.file:
            loc_parts.append(str(self.file))
        if self.line is not None:
            loc_parts.append(str(self.line))
        if self.col is not None:
            loc_parts.append(str(self.col))
        loc_str = ":".join(loc_parts)
        if loc_str:
            return f"{loc_str}: {self.message}"
        return self.message

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
        warnings: Warnings generated during configuration parsing (e.g. unknown keys).
    """
    exclude: list[str] = field(default_factory=list)
    binary_map: dict[str, list[str]] = field(default_factory=dict)
    ignore_issues: list[str] = field(default_factory=list)
    ignore_packages: list[str] = field(default_factory=list)
    history_max_entries: int = 1000
    config_path: Path | None = None
    warnings: list[str] = field(default_factory=list)


def find_config_file(start_path: Path | None = None) -> Path | None:
    """Locate .zerogravity.toml in start_path or any of its parent directories."""
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

    root_candidate = current / CONFIG_FILENAME
    if root_candidate.is_file():
        return root_candidate

    return None


def _find_key_location(file_content: str, key_name: str) -> tuple[int, int]:
    """Find line and column of a key in TOML text."""
    lines = file_content.splitlines()
    for idx, line in enumerate(lines, 1):
        clean = line.strip()
        if clean.startswith("#"):
            continue
        match = re.search(r'\b' + re.escape(key_name) + r'\b', line)
        if match:
            return idx, match.start() + 1
    return 1, 1


def parse_config_data(
    data: dict[str, Any],
    config_path: Path | None = None,
    file_content: str = "",
) -> ZeroGravityConfig:
    """Parse and strictly validate dictionary from .zerogravity.toml."""
    exclude: list[str] = []
    binary_map: dict[str, list[str]] = {}
    ignore_issues: list[str] = []
    ignore_packages: list[str] = []
    history_max_entries: int = 1000
    warnings: list[str] = []

    known_sections = {"scan", "binary_map", "binary-map", "binaries", "ignore", "history"}
    known_scan_keys = {"exclude"}
    known_ignore_keys = {"issues", "categories", "packages"}
    known_history_keys = {"max_entries"}

    for key in data:
        if key not in known_sections:
            close = difflib.get_close_matches(key, ["scan", "binary_map", "ignore", "history"])
            if close:
                msg = f"Unknown section or key '{key}'. Did you mean '{close[0]}'?"
            else:
                msg = f"Unknown section or key '{key}'."
            warnings.append(msg)

    # 1. Scan section
    if "scan" in data:
        scan_section = data["scan"]
        if not isinstance(scan_section, dict):
            line, col = _find_key_location(file_content, "scan")
            raise ConfigError("[scan] must be a section (table)", file=config_path, line=line, col=col)
        for k in scan_section:
            if k not in known_scan_keys:
                close = difflib.get_close_matches(k, list(known_scan_keys))
                if close:
                    msg = f"Unknown key '{k}' in [scan]. Did you mean '{close[0]}'?"
                else:
                    msg = f"Unknown key '{k}' in [scan]."
                warnings.append(msg)
        if "exclude" in scan_section:
            raw_exclude = scan_section["exclude"]
            if not isinstance(raw_exclude, list) or not all(isinstance(x, str) for x in raw_exclude):
                line, col = _find_key_location(file_content, "exclude")
                raise ConfigError("scan.exclude must be a list of strings", file=config_path, line=line, col=col)
            exclude = [str(x).strip() for x in raw_exclude if str(x).strip()]

    # 2. Binary map section
    raw_bmap = data.get("binary_map") or data.get("binary-map") or data.get("binaries")
    if raw_bmap is not None:
        if not isinstance(raw_bmap, dict):
            line, col = _find_key_location(file_content, "binary_map")
            raise ConfigError("binary_map must be a table", file=config_path, line=line, col=col)
        for pkg, bins in raw_bmap.items():
            if isinstance(bins, list):
                if not all(isinstance(b, str) for b in bins):
                    line, col = _find_key_location(file_content, str(pkg))
                    raise ConfigError(f"binary_map.{pkg} must be a list of strings", file=config_path, line=line, col=col)
                binary_map[str(pkg).strip().lower()] = [str(b).strip() for b in bins if str(b).strip()]
            elif isinstance(bins, str):
                binary_map[str(pkg).strip().lower()] = [bins.strip()]
            else:
                line, col = _find_key_location(file_content, str(pkg))
                raise ConfigError(f"binary_map.{pkg} must be a string or list of strings", file=config_path, line=line, col=col)

    # 3. Ignore section
    if "ignore" in data:
        ignore_section = data["ignore"]
        if isinstance(ignore_section, dict):
            for k in ignore_section:
                if k not in known_ignore_keys:
                    close = difflib.get_close_matches(k, list(known_ignore_keys))
                    if close:
                        msg = f"Unknown key '{k}' in [ignore]. Did you mean '{close[0]}'?"
                    else:
                        msg = f"Unknown key '{k}' in [ignore]."
                    warnings.append(msg)
            raw_issues = ignore_section.get("issues") or ignore_section.get("categories")
            if raw_issues is not None:
                if isinstance(raw_issues, list):
                    if not all(isinstance(x, str) for x in raw_issues):
                        line, col = _find_key_location(file_content, "issues")
                        raise ConfigError("ignore.issues must be a list of strings", file=config_path, line=line, col=col)
                    ignore_issues = [str(x).strip().lower() for x in raw_issues if str(x).strip()]
                elif isinstance(raw_issues, str):
                    ignore_issues = [raw_issues.strip().lower()]
                else:
                    line, col = _find_key_location(file_content, "issues")
                    raise ConfigError("ignore.issues must be a list of strings or string", file=config_path, line=line, col=col)

            raw_pkgs = ignore_section.get("packages")
            if raw_pkgs is not None:
                if isinstance(raw_pkgs, list):
                    if not all(isinstance(x, str) for x in raw_pkgs):
                        line, col = _find_key_location(file_content, "packages")
                        raise ConfigError("ignore.packages must be a list of strings", file=config_path, line=line, col=col)
                    ignore_packages = [str(x).strip().lower() for x in raw_pkgs if str(x).strip()]
                elif isinstance(raw_pkgs, str):
                    ignore_packages = [raw_pkgs.strip().lower()]
                else:
                    line, col = _find_key_location(file_content, "packages")
                    raise ConfigError("ignore.packages must be a list of strings or string", file=config_path, line=line, col=col)
        elif isinstance(ignore_section, list):
            if not all(isinstance(x, str) for x in ignore_section):
                line, col = _find_key_location(file_content, "ignore")
                raise ConfigError("ignore list must contain strings", file=config_path, line=line, col=col)
            for item in ignore_section:
                clean_item = str(item).strip().lower()
                if clean_item:
                    ignore_issues.append(clean_item)
                    ignore_packages.append(clean_item)
        else:
            line, col = _find_key_location(file_content, "ignore")
            raise ConfigError("ignore must be a table or list of strings", file=config_path, line=line, col=col)

    # 4. History section
    if "history" in data:
        history_section = data["history"]
        if not isinstance(history_section, dict):
            line, col = _find_key_location(file_content, "history")
            raise ConfigError("[history] must be a section (table)", file=config_path, line=line, col=col)
        for k in history_section:
            if k not in known_history_keys:
                close = difflib.get_close_matches(k, list(known_history_keys))
                if close:
                    msg = f"Unknown key '{k}' in [history]. Did you mean '{close[0]}'?"
                else:
                    msg = f"Unknown key '{k}' in [history]."
                warnings.append(msg)
        if "max_entries" in history_section:
            raw_max = history_section["max_entries"]
            if not isinstance(raw_max, int) or isinstance(raw_max, bool) or raw_max <= 0:
                line, col = _find_key_location(file_content, "max_entries")
                raise ConfigError("history.max_entries must be a positive integer", file=config_path, line=line, col=col)
            history_max_entries = raw_max

    from zerogravity.ui.console import console
    for w in warnings:
        console.print(f"[zg.warning]Warning:[/] {w}")

    return ZeroGravityConfig(
        exclude=exclude,
        binary_map=binary_map,
        ignore_issues=ignore_issues,
        ignore_packages=ignore_packages,
        history_max_entries=history_max_entries,
        config_path=config_path,
        warnings=warnings,
    )


def load_config(path: Path | None = None) -> ZeroGravityConfig:
    """
    Load .zerogravity.toml from given path, file path, or search ancestor directories.
    Raises ConfigError on syntax error or invalid configuration.
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
        content = config_file.read_text(encoding="utf-8")
    except OSError as err:
        raise ConfigError(f"Could not read configuration file: {err}", file=config_file) from err

    try:
        data = tomllib.loads(content)
    except tomllib.TOMLDecodeError as err:
        m = re.search(r"\(at line (\d+), column (\d+)\)", str(err))
        if m:
            line, col = int(m.group(1)), int(m.group(2))
        else:
            line = len(content.splitlines()) or 1
            col = 1
        raise ConfigError(f"TOML syntax error: {err}", file=config_file, line=line, col=col) from err

    return parse_config_data(data, config_path=config_file, file_content=content)


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
