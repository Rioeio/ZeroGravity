from __future__ import annotations

import asyncio
import re
import shutil
import sys
from typing import Dict, List, Optional

from zerogravity.resolver.binary_lookup import (
    get_all_required_system_binaries,
    get_library_metadata,
)
from zerogravity.resolver.models import BinaryProbe

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

async def probe_binary(name: str, command: List[str]) -> BinaryProbe:
    """Probes a binary to get its version and status."""
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
        # Fallback: try library detection for shared libraries
        metadata = get_library_metadata(name)
        if metadata and metadata.get("type") == "library":
            from zerogravity.scanner.lib_detector import detect_library
            return detect_library(name, metadata)
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
    if binaries is None:
        binaries = list(BINARY_MANIFEST.keys())

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
