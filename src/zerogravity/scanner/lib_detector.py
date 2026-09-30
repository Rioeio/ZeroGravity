"""
Library detection fallback chain for shared libraries.

When ``shutil.which`` can't find a dependency (because it's a shared
library, not a PATH binary), this module tries progressively less
portable strategies to determine whether the library is installed:

1. ``pkg-config --exists <name>``     — cross-platform (Linux/macOS/MSYS2)
2. ``ldconfig -p | grep <name>``      — Linux shared-library cache
3. ``dpkg -l <apt_name>``             — Debian/Ubuntu package manager
4. ``rpm -q <rpm_name>``              — RHEL/Fedora package manager
5. ``brew list <brew_name>``          — macOS Homebrew

Each strategy returns a :class:`BinaryProbe` on success or ``None`` to
let the next strategy try.
"""

from __future__ import annotations

import platform
import re
import shutil
import subprocess
from typing import Any

from zerogravity.resolver.models import BinaryProbe

_TIMEOUT = 3.0  # seconds

# ── Memoization caches per scan run ─────────────────────────────────────────
_pkg_config_cache: dict[str, BinaryProbe | None] = {}
_ldconfig_cache: dict[str, BinaryProbe | None] = {}
_ldconfig_stdout_cache: str | None = None
_dpkg_cache: dict[str, BinaryProbe | None] = {}
_rpm_cache: dict[str, BinaryProbe | None] = {}
_brew_cache: dict[str, BinaryProbe | None] = {}
_detect_library_cache: dict[str, BinaryProbe] = {}


def clear_detection_cache() -> None:
    """Clear all memoized library detection results."""
    global _ldconfig_stdout_cache
    _pkg_config_cache.clear()
    _ldconfig_cache.clear()
    _ldconfig_stdout_cache = None
    _dpkg_cache.clear()
    _rpm_cache.clear()
    _brew_cache.clear()
    _detect_library_cache.clear()


# ── Individual detection strategies ─────────────────────────────────────────

def _try_pkg_config(name: str, metadata: dict[str, Any]) -> BinaryProbe | None:
    """Try ``pkg-config --exists`` then ``--modversion`` to detect a library."""
    if name in _pkg_config_cache:
        return _pkg_config_cache[name]

    pc_name = metadata.get("pkg_config")
    if not pc_name:
        _pkg_config_cache[name] = None
        return None
    if not shutil.which("pkg-config"):
        _pkg_config_cache[name] = None
        return None
    try:
        result = subprocess.run(
            ["pkg-config", "--exists", pc_name],
            capture_output=True,
            timeout=_TIMEOUT,
        )
        if result.returncode != 0:
            _pkg_config_cache[name] = None
            return None
        # Library exists — try to get its version
        ver_result = subprocess.run(
            ["pkg-config", "--modversion", pc_name],
            capture_output=True,
            text=True,
            timeout=_TIMEOUT,
        )
        version = ver_result.stdout.strip() if ver_result.returncode == 0 else None
        probe = BinaryProbe(
            name=name,
            installed=True,
            path=f"pkg-config:{pc_name}",
            version=version,
        )
        _pkg_config_cache[name] = probe
        return probe
    except (subprocess.TimeoutExpired, OSError):
        _pkg_config_cache[name] = None
        return None


def _try_ldconfig(name: str, metadata: dict[str, Any]) -> BinaryProbe | None:
    """Try ``ldconfig -p`` to find a shared library in the Linux ld cache."""
    global _ldconfig_stdout_cache
    if platform.system() != "Linux":
        return None
    if name in _ldconfig_cache:
        return _ldconfig_cache[name]
    if not shutil.which("ldconfig"):
        _ldconfig_cache[name] = None
        return None
    try:
        if _ldconfig_stdout_cache is None:
            result = subprocess.run(
                ["ldconfig", "-p"],
                capture_output=True,
                text=True,
                timeout=_TIMEOUT,
            )
            if result.returncode != 0:
                _ldconfig_cache[name] = None
                return None
            _ldconfig_stdout_cache = result.stdout

        # Search for a line like: libfoo.so.1 (libc6,...) => /usr/lib/...
        pattern = re.compile(rf"\b{re.escape(name)}\.so", re.IGNORECASE)
        for line in _ldconfig_stdout_cache.splitlines():
            if pattern.search(line):
                # Extract path after " => "
                path_match = re.search(r"=>\s*(\S+)", line)
                lib_path = path_match.group(1) if path_match else f"ldconfig:{name}"
                probe = BinaryProbe(
                    name=name,
                    installed=True,
                    path=lib_path,
                )
                _ldconfig_cache[name] = probe
                return probe
        _ldconfig_cache[name] = None
        return None
    except (subprocess.TimeoutExpired, OSError):
        _ldconfig_cache[name] = None
        return None


def _try_dpkg(name: str, metadata: dict[str, Any]) -> BinaryProbe | None:
    """Try ``dpkg -l`` on Debian/Ubuntu to check if a package is installed."""
    if name in _dpkg_cache:
        return _dpkg_cache[name]

    apt_name = metadata.get("apt")
    if not apt_name:
        _dpkg_cache[name] = None
        return None
    if not shutil.which("dpkg"):
        _dpkg_cache[name] = None
        return None
    try:
        result = subprocess.run(
            ["dpkg", "-l", apt_name],
            capture_output=True,
            text=True,
            timeout=_TIMEOUT,
        )
        if result.returncode != 0:
            _dpkg_cache[name] = None
            return None
        # Look for a line starting with "ii " (installed)
        for line in result.stdout.splitlines():
            if line.startswith("ii "):
                parts = line.split()
                version = parts[2] if len(parts) >= 3 else None
                probe = BinaryProbe(
                    name=name,
                    installed=True,
                    path=f"dpkg:{apt_name}",
                    version=version,
                )
                _dpkg_cache[name] = probe
                return probe
        _dpkg_cache[name] = None
        return None
    except (subprocess.TimeoutExpired, OSError):
        _dpkg_cache[name] = None
        return None


def _try_rpm(name: str, metadata: dict[str, Any]) -> BinaryProbe | None:
    """Try ``rpm -q`` on RHEL/Fedora to check if a package is installed."""
    if name in _rpm_cache:
        return _rpm_cache[name]

    rpm_name = metadata.get("rpm")
    if not rpm_name:
        _rpm_cache[name] = None
        return None
    if not shutil.which("rpm"):
        _rpm_cache[name] = None
        return None
    try:
        result = subprocess.run(
            ["rpm", "-q", rpm_name],
            capture_output=True,
            text=True,
            timeout=_TIMEOUT,
        )
        if result.returncode != 0:
            _rpm_cache[name] = None
            return None
        output = result.stdout.strip()
        # rpm -q prints "<name>-<version>-<release>.<arch>"
        ver_match = re.search(r"-(\d+\.\d+[\.\d]*)", output)
        version = ver_match.group(1) if ver_match else None
        probe = BinaryProbe(
            name=name,
            installed=True,
            path=f"rpm:{rpm_name}",
            version=version,
        )
        _rpm_cache[name] = probe
        return probe
    except (subprocess.TimeoutExpired, OSError):
        _rpm_cache[name] = None
        return None


def _try_brew(name: str, metadata: dict[str, Any]) -> BinaryProbe | None:
    """Try ``brew list`` on macOS to check if a Homebrew formula is installed."""
    if name in _brew_cache:
        return _brew_cache[name]

    brew_name = metadata.get("brew")
    if not brew_name:
        _brew_cache[name] = None
        return None
    if platform.system() != "Darwin":
        return None
    if not shutil.which("brew"):
        _brew_cache[name] = None
        return None
    try:
        result = subprocess.run(
            ["brew", "list", brew_name],
            capture_output=True,
            text=True,
            timeout=_TIMEOUT,
        )
        if result.returncode != 0:
            _brew_cache[name] = None
            return None
        probe = BinaryProbe(
            name=name,
            installed=True,
            path=f"brew:{brew_name}",
        )
        _brew_cache[name] = probe
        return probe
    except (subprocess.TimeoutExpired, OSError):
        _brew_cache[name] = None
        return None


def _try_which(name: str, metadata: dict[str, Any]) -> BinaryProbe | None:
    """Final fallback: plain ``shutil.which``."""
    path = shutil.which(name)
    if path:
        return BinaryProbe(name=name, installed=True, path=path)
    return None


# ── Ordered strategy list ───────────────────────────────────────────────────
DETECTION_STRATEGIES = [
    _try_pkg_config,
    _try_ldconfig,
    _try_dpkg,
    _try_rpm,
    _try_brew,
]


# ── Public entry point ──────────────────────────────────────────────────────

def detect_library(name: str, metadata: dict[str, Any]) -> BinaryProbe:
    """Detect whether a shared library is installed using a fallback chain.

    Tries each strategy in :data:`DETECTION_STRATEGIES` order and returns
    the first successful :class:`BinaryProbe`.  If every strategy fails,
    returns ``BinaryProbe(name=name, installed=False)``.

    Parameters
    ----------
    name:
        The canonical dependency name (e.g. ``"libjpeg"``).
    metadata:
        Detection hints dict from ``get_library_metadata()`` containing
        ``type``, ``pkg_config``, ``apt``, ``rpm``, ``brew`` keys.
    """
    if name in _detect_library_cache:
        return _detect_library_cache[name]

    for strategy in DETECTION_STRATEGIES:
        probe = strategy(name, metadata)
        if probe is not None:
            _detect_library_cache[name] = probe
            return probe

    probe = BinaryProbe(name=name, installed=False)
    _detect_library_cache[name] = probe
    return probe
