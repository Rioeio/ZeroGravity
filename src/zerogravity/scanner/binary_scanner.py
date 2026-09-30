from __future__ import annotations

import asyncio
import re
import shutil
import sys
from typing import Dict, List, Optional

from zerogravity.parsers.base import ProjectManifest
from zerogravity.resolver.binary_lookup import (
    get_all_required_system_binaries,
    get_library_metadata,
    lookup_system_deps,
)
from zerogravity.resolver.models import BinaryProbe

BASELINE_RUNTIME_BINARIES: list[str] = [
    "node",
    "python3",
    "python",
    "npm",
    "pip",
    "git",
    "docker",
]

CORE_SYSTEM_BINARIES: list[str] = [
    "node",
    "python3",
    "python",
    "npm",
    "pip",
    "docker",
    "git",
    "openssl",
    "gcc",
    "make",
    "go",
    "rust",
    "rustc",
    "cargo",
    "ruby",
    "java",
]

BINARY_MANIFEST = {
    "node": ["node", "--version"],
    "python3": ["python3", "--version"],
    "python": ["python", "--version"],
    "npm": ["npm", "--version"],
    "pip": ["pip", "--version"],
    "docker": ["docker", "--version"],
    "git": ["git", "--version"],
    "openssl": ["openssl", "version"],
    "gcc": ["gcc", "--version"],
    "make": ["make", "--version"],
    "go": ["go", "version"],
    "rust": ["rustc", "--version"],
    "rustc": ["rustc", "--version"],
    "cargo": ["cargo", "--version"],
    "ruby": ["ruby", "--version"],
    "java": ["java", "-version"],
}

for _binary in get_all_required_system_binaries():
    if _binary not in BINARY_MANIFEST:
        BINARY_MANIFEST[_binary] = [_binary, "--version"]


def compute_scoped_binaries(
    manifests: list[ProjectManifest],
    custom_map: dict[str, list[str]] | None = None,
) -> list[str]:
    """Compute project-relevant binaries and libraries scoped to manifests.

    Unions baseline runtime binaries with system dependencies required by all
    package dependencies across all manifests, plus any declared engine constraints.
    """
    scoped: set[str] = set(BASELINE_RUNTIME_BINARIES)
    for manifest in manifests:
        for engine in manifest.engine_constraints.keys():
            scoped.add(engine)
        reqs = lookup_system_deps(manifest.dependencies, custom_map=custom_map)
        for req in reqs:
            scoped.add(req.required_binary)
    return sorted(scoped)


async def probe_binary(name: str, command: List[str]) -> BinaryProbe:
    """Probes a binary to get its version and status."""
    # Shared libraries (e.g. openssl, libjpeg) must be detected via
    # pkg-config/ldconfig/package managers rather than searching PATH.
    # Checking library metadata first prevents naming collisions where a CLI tool
    # (e.g. /usr/bin/openssl) shadows a missing development library (e.g. libssl-dev).
    metadata = get_library_metadata(name)
    if metadata and metadata.get("type") == "library":
        from zerogravity.scanner.lib_detector import detect_library
        return detect_library(name, metadata)

    # Handle Windows specific logic for python3
    if sys.platform == "win32" and name == "python3":
        path = shutil.which("python3")
        if not path:
            path = shutil.which("python")
            if path:
                command = ["python", "--version"]
    elif name == "rust":
        path = shutil.which("rustc") or shutil.which("rust")
        if path:
            command = ["rustc", "--version"]
    else:
        path = shutil.which(name)

    if not path:
        return BinaryProbe(name=name, installed=False, path=None, version=None, error=None)

    exec_cmd = list(command)
    if sys.platform == "win32" and path:
        if path.lower().endswith((".cmd", ".bat")):
            exec_cmd = ["cmd.exe", "/c", path] + command[1:]

    try:
        proc = await asyncio.create_subprocess_exec(
            *exec_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        stdout_data, stderr_data = await asyncio.wait_for(proc.communicate(), timeout=5.0)

        stdout_str = stdout_data.decode("utf-8", errors="ignore").strip()
        stderr_str = stderr_data.decode("utf-8", errors="ignore").strip()

        output = stdout_str or stderr_str

        # java outputs version to stderr, handle differently? it will be in output
        if proc.returncode != 0 and name != "java":
            detail = output or "no output"
            return BinaryProbe(
                name=name,
                installed=True,
                path=path,
                version=None,
                error=f"'{' '.join(command)}' exited with code {proc.returncode}: {detail}",
            )

        match = re.search(r"(\d+\.\d+(?:\.\d+)?)", output)
        version = match.group(1) if match else None

        return BinaryProbe(name=name, installed=True, path=path, version=version, error=None)

    except asyncio.TimeoutError:
        return BinaryProbe(
            name=name,
            installed=True,
            path=path,
            version=None,
            error=f"Timed out after 5s waiting for '{' '.join(command)}'",
        )
    except PermissionError as e:
        return BinaryProbe(
            name=name,
            installed=True,
            path=path,
            version=None,
            error=f"Permission denied running '{' '.join(command)}': {e}",
        )
    except Exception as e:
        return BinaryProbe(
            name=name,
            installed=True,
            path=path,
            version=None,
            error=f"Failed to probe '{' '.join(command)}': {e}",
        )


async def run_full_scan(binaries: Optional[List[str]] = None) -> Dict[str, BinaryProbe]:
    """Runs a full asynchronous scan of all or specified binaries."""
    from zerogravity.scanner.lib_detector import clear_detection_cache

    clear_detection_cache()

    if binaries is None:
        binaries = list(CORE_SYSTEM_BINARIES)

    tasks = []
    for binary in binaries:
        if binary in BINARY_MANIFEST:
            tasks.append(probe_binary(binary, BINARY_MANIFEST[binary]))
        else:
            tasks.append(probe_binary(binary, [binary, "--version"]))

    results = await asyncio.gather(*tasks)
    return {probe.name: probe for probe in results}


def run_scan_sync(binaries: Optional[List[str]] = None) -> Dict[str, BinaryProbe]:
    """Synchronous wrapper for run_full_scan."""
    return asyncio.run(run_full_scan(binaries))
