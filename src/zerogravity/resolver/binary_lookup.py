from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List

from zerogravity.parsers.base import Dependency

# Dictionary mapping package names to required system binaries
SYSTEM_DEPENDENCY_MAP: Dict[str, List[str]] = {
    # Python packages
    "cryptography": ["openssl"],
    "psycopg2": ["pg_config"],
    "psycopg2-binary": [],  # pre-compiled, no system deps
    "pillow": ["libjpeg", "zlib"],
    "lxml": ["libxml2", "libxslt"],
    "mysqlclient": ["mysql_config"],
    "bcrypt": ["gcc"],  # Python bcrypt
    "cffi": ["gcc", "libffi"],
    "pynacl": ["libsodium"],

    # Node packages
    "node-gyp": ["python", "make", "gcc"],
    "canvas": ["pkg-config", "cairo"],
    "sharp": ["vips"],
    "sqlite3": ["python", "make", "gcc"],
}

@dataclass
class SystemDepRequirement:
    """Represents a system binary required by a package dependency."""
    package_name: str
    required_binary: str
    description: str

def lookup_system_deps(dependencies: List[Dependency]) -> List[SystemDepRequirement]:
    """
    Takes a list of Dependencies from a manifest and returns a list
    of required system binaries based on the lookup table.
    """
    requirements = []

    for dep in dependencies:
        pkg_name = dep.name.lower()
        if pkg_name in SYSTEM_DEPENDENCY_MAP:
            binaries = SYSTEM_DEPENDENCY_MAP[pkg_name]
            for binary in binaries:
                requirements.append(SystemDepRequirement(
                    package_name=dep.name,
                    required_binary=binary,
                    description=f"System binary '{binary}' is required by package '{dep.name}'"
                ))

    return requirements

def get_all_known_packages() -> List[str]:
    """
    Returns a list of all package names in the lookup table.
    """
    return list(SYSTEM_DEPENDENCY_MAP.keys())

def get_all_required_system_binaries() -> list[str]:
    """
    Returns a list of all unique binary names listed in SYSTEM_DEPENDENCY_MAP.values().
    """
    binaries = set()
    for req_bins in SYSTEM_DEPENDENCY_MAP.values():
        binaries.update(req_bins)
    return sorted(list(binaries))
