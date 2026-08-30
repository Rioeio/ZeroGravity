from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from importlib import resources
from typing import Any, Dict, List

from zerogravity.parsers.base import Dependency

logger = logging.getLogger(__name__)

# ── Schema constants ────────────────────────────────────────────────────────
_REQUIRED_TOP_KEYS = {"version", "packages", "library_metadata"}
_REQUIRED_META_KEYS = {"type", "pkg_config", "apt", "rpm", "brew"}
_VALID_DEP_TYPES = {"binary", "library"}
_SUPPORTED_SCHEMA_VERSION = 1


# ── Schema validation ──────────────────────────────────────────────────────
class SystemDepsSchemaError(Exception):
    """Raised when system_deps.json fails schema validation."""


def _validate_schema(data: Any) -> None:
    """Validate the loaded JSON against the expected schema.

    Raises :class:`SystemDepsSchemaError` with a clear message on any
    structural or type violation so mis-authored data files surface
    immediately rather than causing silent look-up misses at runtime.
    """
    if not isinstance(data, dict):
        raise SystemDepsSchemaError(
            f"system_deps.json: root must be a JSON object, got {type(data).__name__}"
        )

    missing_top = _REQUIRED_TOP_KEYS - data.keys()
    if missing_top:
        raise SystemDepsSchemaError(
            f"system_deps.json: missing required top-level keys: {sorted(missing_top)}"
        )

    version = data["version"]
    if not isinstance(version, int):
        raise SystemDepsSchemaError(
            f"system_deps.json: 'version' must be an integer, got {type(version).__name__}"
        )
    if version != _SUPPORTED_SCHEMA_VERSION:
        raise SystemDepsSchemaError(
            f"system_deps.json: unsupported schema version {version} "
            f"(expected {_SUPPORTED_SCHEMA_VERSION})"
        )

    packages = data["packages"]
    if not isinstance(packages, dict):
        raise SystemDepsSchemaError(
            f"system_deps.json: 'packages' must be a JSON object, got {type(packages).__name__}"
        )
    for pkg_name, deps in packages.items():
        if not isinstance(deps, list):
            raise SystemDepsSchemaError(
                f"system_deps.json: packages['{pkg_name}'] must be a list, "
                f"got {type(deps).__name__}"
            )
        for dep in deps:
            if not isinstance(dep, str):
                raise SystemDepsSchemaError(
                    f"system_deps.json: packages['{pkg_name}'] contains "
                    f"non-string element: {dep!r}"
                )

    metadata = data["library_metadata"]
    if not isinstance(metadata, dict):
        raise SystemDepsSchemaError(
            f"system_deps.json: 'library_metadata' must be a JSON object, "
            f"got {type(metadata).__name__}"
        )
    for dep_name, meta in metadata.items():
        if not isinstance(meta, dict):
            raise SystemDepsSchemaError(
                f"system_deps.json: library_metadata['{dep_name}'] must be "
                f"a JSON object, got {type(meta).__name__}"
            )
        missing_meta = _REQUIRED_META_KEYS - meta.keys()
        if missing_meta:
            raise SystemDepsSchemaError(
                f"system_deps.json: library_metadata['{dep_name}'] missing "
                f"required keys: {sorted(missing_meta)}"
            )
        dep_type = meta.get("type")
        if dep_type not in _VALID_DEP_TYPES:
            raise SystemDepsSchemaError(
                f"system_deps.json: library_metadata['{dep_name}'].type must "
                f"be one of {sorted(_VALID_DEP_TYPES)}, got {dep_type!r}"
            )


# ── Data loading ────────────────────────────────────────────────────────────
def _load_system_deps() -> dict[str, Any]:
    """Load and validate system_deps.json from the package data directory."""
    try:
        data_text = resources.files("zerogravity.data").joinpath(
            "system_deps.json"
        ).read_text(encoding="utf-8")
    except (FileNotFoundError, ModuleNotFoundError) as exc:
        raise SystemDepsSchemaError(
            f"system_deps.json not found in zerogravity.data package: {exc}"
        ) from exc

    try:
        data = json.loads(data_text)
    except json.JSONDecodeError as exc:
        raise SystemDepsSchemaError(
            f"system_deps.json contains invalid JSON: {exc}"
        ) from exc

    _validate_schema(data)
    return data


_DATA = _load_system_deps()

# Dictionary mapping package names to required system binaries
# (preserves the original module-level name so all existing callers work)
SYSTEM_DEPENDENCY_MAP: Dict[str, List[str]] = _DATA["packages"]

# Per-dependency detection metadata (type, pkg-config, apt, rpm, brew names)
_LIBRARY_METADATA: Dict[str, Dict[str, Any]] = _DATA["library_metadata"]


# ── Public API (unchanged signatures) ──────────────────────────────────────

@dataclass
class SystemDepRequirement:
    """Represents a system binary required by a package dependency."""
    package_name: str
    required_binary: str
    description: str


def lookup_system_deps(
    dependencies: List[Dependency],
    custom_map: Dict[str, List[str]] | None = None,
) -> List[SystemDepRequirement]:
    """
    Takes a list of Dependencies from a manifest and returns a list
    of required system binaries based on the lookup table and custom overrides.

    Resolution precedence (unchanged — preserves dedup / override behaviour):
    1. ``custom_map[pkg_name]`` when ``custom_map`` is not None and has the key.
    2. ``SYSTEM_DEPENDENCY_MAP[pkg_name]`` from the JSON data file.
    3. Skip the dependency (no system-dep requirement emitted).
    """
    requirements: list[SystemDepRequirement] = []

    for dep in dependencies:
        pkg_name = dep.name.lower()
        if custom_map is not None and pkg_name in custom_map:
            binaries = custom_map[pkg_name]
        elif pkg_name in SYSTEM_DEPENDENCY_MAP:
            binaries = SYSTEM_DEPENDENCY_MAP[pkg_name]
        else:
            continue

        for binary in binaries:
            requirements.append(SystemDepRequirement(
                package_name=dep.name,
                required_binary=binary,
                description=f"System binary '{binary}' is required by package '{dep.name}'"
            ))

    return requirements


def get_all_known_packages() -> List[str]:
    """Returns a list of all package names in the lookup table."""
    return list(SYSTEM_DEPENDENCY_MAP.keys())


def get_all_required_system_binaries() -> list[str]:
    """Returns a list of all unique binary names listed in SYSTEM_DEPENDENCY_MAP.values()."""
    binaries: set[str] = set()
    for req_bins in SYSTEM_DEPENDENCY_MAP.values():
        binaries.update(req_bins)
    return sorted(list(binaries))


def get_library_metadata(dep_name: str) -> dict[str, Any] | None:
    """Return detection hints for *dep_name*, or ``None`` if unknown.

    The returned dict contains ``type`` (``"binary"`` or ``"library"``),
    ``pkg_config``, ``apt``, ``rpm``, and ``brew`` keys.
    """
    return _LIBRARY_METADATA.get(dep_name)
