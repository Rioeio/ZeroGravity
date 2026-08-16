from __future__ import annotations

import asyncio
import re
import shutil
import sys
from typing import Dict, List, Optional

from zerogravity.resolver.binary_lookup import get_all_required_system_binaries
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
    else:
        path = shutil.which(name)

    if not path:
        return BinaryProbe(name=name, installed=False, path=None, version=None, error=None)

    try:
        proc = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        stdout_data, stderr_data = await asyncio.wait_for(proc.communicate(), timeout=2.0)

        stdout_str = stdout_data.decode('utf-8', errors='ignore').strip()
        stderr_str = stderr_data.decode('utf-8', errors='ignore').strip()

        output = stdout_str or stderr_str

        # java outputs version to stderr, handle differently? it will be in output
        if proc.returncode != 0 and name != "java":
            detail = output or "no output"
            return BinaryProbe(
                name=name, installed=True, path=path, version=None,
                error=f"'{' '.join(command)}' exited with code {proc.returncode}: {detail}",
            )

        match = re.search(r'(\d+\.\d+\.\d+)', output)
        if match:
            version = match.group(1)
        else:
            version = None

        return BinaryProbe(name=name, installed=True, path=path, version=version, error=None)

    except asyncio.TimeoutError:
        return BinaryProbe(
            name=name, installed=True, path=path, version=None,
            error=f"Timed out after 2s waiting for '{' '.join(command)}'",
        )
    except PermissionError as e:
        return BinaryProbe(
            name=name, installed=True, path=path, version=None,
            error=f"Permission denied running '{' '.join(command)}': {e}",
        )
    except Exception as e:
        return BinaryProbe(
            name=name, installed=True, path=path, version=None,
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
    """Synchronous wrapper for run_full_scan.

    Uses WindowsSelectorEventLoopPolicy on Windows to avoid
    ProactorEventLoop cleanup warnings with subprocess pipes.
    """
    if sys.platform == "win32":
        # SelectorEventLoop avoids ProactorBasePipeTransport __del__ warnings
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    try:
        return asyncio.run(run_full_scan(binaries))
    finally:
        if sys.platform == "win32":
            asyncio.set_event_loop_policy(None)
