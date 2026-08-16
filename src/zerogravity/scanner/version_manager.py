from __future__ import annotations

import asyncio
import os
import shutil
from typing import Any, Dict

from zerogravity.resolver.models import VersionManagerInfo

VERSION_MANAGERS: Dict[str, Dict[str, Any]] = {
    "nvm": {
        "env_var": "NVM_DIR",
        "binary": "nvm.exe" if os.name == "nt" else "nvm",
        "version_cmd": ["nvm", "current"],
        "list_cmd": ["nvm", "ls"]
    },
    "pyenv": {
        "env_var": "PYENV_ROOT",
        "binary": "pyenv",
        "version_cmd": ["pyenv", "version-name"],
        "list_cmd": ["pyenv", "versions", "--bare"]
    },
    "asdf": {
        "env_var": "ASDF_DIR",
        "binary": "asdf",
        "version_cmd": None,
        "list_cmd": ["asdf", "list"]
    },
    "rbenv": {
        "env_var": "RBENV_ROOT",
        "binary": "rbenv",
        "version_cmd": ["rbenv", "version-name"],
        "list_cmd": ["rbenv", "versions", "--bare"]
    },
    "rustup": {
        "env_var": "RUSTUP_HOME",
        "binary": "rustup",
        "version_cmd": ["rustup", "default"],
        "list_cmd": ["rustup", "toolchain", "list"]
    }
}

async def detect_version_manager(name: str, detection_config: Dict[str, Any]) -> VersionManagerInfo:
    """Detects a single version manager and queries its installed and active versions."""
    env_var = detection_config.get("env_var")
    binary_name = detection_config.get("binary")
    version_cmd = detection_config.get("version_cmd")
    list_cmd = detection_config.get("list_cmd")

    root_path = os.environ.get(env_var) if env_var else None
    binary_path = shutil.which(binary_name) if binary_name else None

    detected = bool(root_path or binary_path)
    active_version = None
    installed_versions = []

    if detected:
        if version_cmd:
            try:
                proc = await asyncio.create_subprocess_exec(
                    *version_cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=2.0)
                if proc.returncode == 0:
                    active_version = stdout.decode("utf-8", errors="ignore").strip()
            except Exception:
                pass

        if list_cmd:
            try:
                proc = await asyncio.create_subprocess_exec(
                    *list_cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=2.0)
                if proc.returncode == 0:
                    lines = stdout.decode("utf-8", errors="ignore").splitlines()
                    installed_versions = [line.strip().strip("*").strip() for line in lines if line.strip()]
            except Exception:
                pass

    return VersionManagerInfo(
        name=name,
        detected=detected,
        root_path=root_path,
        active_version=active_version,
        installed_versions=installed_versions
    )

async def detect_all_managers() -> Dict[str, VersionManagerInfo]:
    """Concurrently detects all configured version managers."""
    tasks = []
    names = []
    for name, config in VERSION_MANAGERS.items():
        names.append(name)
        tasks.append(detect_version_manager(name, config))

    results = await asyncio.gather(*tasks)
    return {name: result for name, result in zip(names, results)}

def detect_all_managers_sync() -> Dict[str, VersionManagerInfo]:
    """Synchronous wrapper for detect_all_managers."""
    return asyncio.run(detect_all_managers())
