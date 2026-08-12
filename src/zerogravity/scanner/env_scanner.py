from __future__ import annotations

import os
import platform
from pathlib import Path
from typing import Dict, List

def scan_environment() -> Dict[str, str]:
    """Scans and returns relevant environment variables."""
    target_vars = [
        "PATH", "PYTHONPATH", "NODE_PATH", "GOPATH", "GOROOT", 
        "JAVA_HOME", "CARGO_HOME", "RUSTUP_HOME", "NVM_DIR", 
        "PYENV_ROOT", "ASDF_DIR", "RBENV_ROOT", "VIRTUAL_ENV", 
        "CONDA_PREFIX"
    ]
    result = {}
    for var in target_vars:
        val = os.environ.get(var)
        if val is not None:
            result[var] = val
    return result

def get_platform_info() -> Dict[str, str]:
    """Returns OS and platform information."""
    return {
        "os_name": platform.system(),
        "os_version": platform.release(),
        "architecture": platform.machine(),
        "python_version": platform.python_version(),
        "hostname": platform.node(),
    }

def scan_path_directories() -> List[str]:
    """Splits PATH and validates which directories exist on disk."""
    path_var = os.environ.get("PATH", "")
    separator = ";" if platform.system() == "Windows" else ":"
    dirs = path_var.split(separator)
    
    valid_dirs = []
    for d in dirs:
        if not d:
            continue
        p = Path(d)
        if p.exists() and p.is_dir():
            valid_dirs.append(str(p))
            
    return valid_dirs
