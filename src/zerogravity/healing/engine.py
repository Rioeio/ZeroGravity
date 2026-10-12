from __future__ import annotations

import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from zerogravity.config import ZeroGravityConfig
from zerogravity.resolver.models import Issue, IssueCategory, ResolutionReport, SystemSnapshot


@dataclass
class RemediationPlan:
    """Represents a planned remediation action."""
    issue: Issue
    manager_name: str
    command: list[str]
    description: str


_EXACT_VERSION_RE = re.compile(r"^v?(\d+\.\d+\.\d+)$")
_LEADING_VERSION_RE = re.compile(r"(\d+)(?:\.(\d+))?")

DEFAULT_PRIORITIES: dict[str, list[str]] = {
    "node": ["fnm", "volta", "mise", "nvm-windows", "nvm", "asdf"],
    "python": ["uv", "pyenv-win", "pyenv", "mise", "asdf"],
    "rust": ["rustup", "mise", "asdf"],
}


def _resolve_target_version(spec: str) -> Optional[str]:
    """
    Best-effort extraction of a version a manager can actually install
    from a raw constraint string ("^18.2.0", ">=18.0.0,<19.0.0", "18.x", "3.11").
    """
    if not spec:
        return None

    spec = spec.strip()
    exact = _EXACT_VERSION_RE.match(spec)
    if exact:
        return exact.group(1)

    first_component = re.split(r"\|\||,", spec)[0].strip()
    match = _LEADING_VERSION_RE.search(first_component)
    if not match:
        return None

    major, minor = match.group(1), match.group(2)
    if first_component.startswith("~") and minor:
        return f"{major}.{minor}"
    return major


def _find_nvm_script(snapshot: SystemSnapshot) -> Optional[Path]:
    """Locate nvm.sh from the NVM_DIR recorded on the snapshot."""
    nvm_info = snapshot.version_managers.get("nvm")
    if not nvm_info or not nvm_info.root_path:
        return None
    script = Path(nvm_info.root_path) / "nvm.sh"
    return script if script.is_file() else None


def _is_manager_available(name: str, snapshot: SystemSnapshot) -> bool:
    """Check if a version manager is detected on the system."""
    info = snapshot.version_managers.get(name)
    if info is not None:
        if name == "nvm" and info.root_path:
            return (Path(info.root_path) / "nvm.sh").is_file()
        return bool(info.detected)

    if name == "nvm-windows":
        if sys.platform != "win32":
            return False
        path = shutil.which("nvm.exe") or shutil.which("nvm")
        return bool(path and Path(path).name.lower() in ("nvm.exe", "nvm.bat", "nvm.cmd"))

    if name == "pyenv-win":
        if sys.platform != "win32":
            return False
        path = shutil.which("pyenv.bat")
        return bool(path and Path(path).name.lower() == "pyenv.bat")

    if name == "nvm":
        if sys.platform == "win32":
            return bool(shutil.which("nvm.exe") or shutil.which("nvm"))
        return _find_nvm_script(snapshot) is not None

    path = shutil.which(name)
    if not path:
        return False
    stem = Path(path).stem.lower()
    return stem == name.lower() or name.lower() in stem


def _order_managers(supported: list[str], prefer: list[str]) -> list[str]:
    """Order candidate managers: preferred ones first in specified order, then default."""
    ordered: list[str] = []
    for p in prefer:
        p_clean = p.strip().lower()
        if p_clean in supported and p_clean not in ordered:
            ordered.append(p_clean)
    for s in supported:
        if s not in ordered:
            ordered.append(s)
    return ordered


def _create_plans(manager: str, issue: Issue, target_version: str, binary: str) -> list[RemediationPlan]:
    """Build concrete remediation plans for the specified version manager."""
    plans: list[RemediationPlan] = []
    if manager == "uv":
        plans.append(RemediationPlan(
            issue=issue,
            manager_name="uv",
            command=["uv", "python", "install", target_version],
            description=f"Install Python {target_version} via uv",
        ))
    elif manager == "fnm":
        plans.append(RemediationPlan(
            issue=issue,
            manager_name="fnm",
            command=["fnm", "install", target_version],
            description=f"Install Node.js {target_version} via fnm",
        ))
        plans.append(RemediationPlan(
            issue=issue,
            manager_name="fnm",
            command=["fnm", "use", target_version],
            description=f"Use Node.js {target_version} via fnm",
        ))
    elif manager == "volta":
        plans.append(RemediationPlan(
            issue=issue,
            manager_name="volta",
            command=["volta", "install", f"node@{target_version}"],
            description=f"Install Node.js {target_version} via volta",
        ))
    elif manager == "mise":
        plans.append(RemediationPlan(
            issue=issue,
            manager_name="mise",
            command=["mise", "install", f"{binary}@{target_version}"],
            description=f"Install {binary.capitalize()} {target_version} via mise",
        ))
        plans.append(RemediationPlan(
            issue=issue,
            manager_name="mise",
            command=["mise", "use", f"{binary}@{target_version}"],
            description=f"Use {binary.capitalize()} {target_version} via mise",
        ))
    elif manager in ("nvm", "nvm-windows"):
        plans.append(RemediationPlan(
            issue=issue,
            manager_name=manager,
            command=["nvm", "install", target_version],
            description=f"Install Node.js {target_version} via nvm",
        ))
        plans.append(RemediationPlan(
            issue=issue,
            manager_name=manager,
            command=["nvm", "use", target_version],
            description=f"Use Node.js {target_version} via nvm",
        ))
    elif manager == "pyenv":
        plans.append(RemediationPlan(
            issue=issue,
            manager_name="pyenv",
            command=["pyenv", "install", "-s", target_version],
            description=f"Install Python {target_version} via pyenv",
        ))
        plans.append(RemediationPlan(
            issue=issue,
            manager_name="pyenv",
            command=["pyenv", "local", target_version],
            description=f"Set local Python {target_version} via pyenv",
        ))
    elif manager == "pyenv-win":
        plans.append(RemediationPlan(
            issue=issue,
            manager_name="pyenv-win",
            command=["pyenv", "install", target_version],
            description=f"Install Python {target_version} via pyenv",
        ))
        plans.append(RemediationPlan(
            issue=issue,
            manager_name="pyenv-win",
            command=["pyenv", "local", target_version],
            description=f"Set local Python {target_version} via pyenv",
        ))
    elif manager == "rustup":
        plans.append(RemediationPlan(
            issue=issue,
            manager_name="rustup",
            command=["rustup", "override", "set", target_version],
            description=f"Set Rust {target_version} via rustup override",
        ))
    elif manager == "asdf":
        plugin = "nodejs" if binary == "node" else binary
        plans.append(RemediationPlan(
            issue=issue,
            manager_name="asdf",
            command=["asdf", "install", plugin, target_version],
            description=f"Install {binary.capitalize()} {target_version} via asdf",
        ))
        plans.append(RemediationPlan(
            issue=issue,
            manager_name="asdf",
            command=["asdf", "local", plugin, target_version],
            description=f"Set local {binary.capitalize()} {target_version} via asdf",
        ))
    return plans


class HealingEngine:
    """
    Engine responsible for self-healing runtime environment mismatches.

    Default priorities:
      - Node.js: fnm > volta > mise > nvm-windows > nvm > asdf
      - Python:  uv > pyenv-win > pyenv > mise > asdf
      - Rust:    rustup > mise > asdf
    Overridable via config [healing] prefer = [...].
    """

    def __init__(self, prefer: list[str] | None = None) -> None:
        self.prefer = prefer or []

    def plan_remediations(
        self,
        report: ResolutionReport,
        snapshot: SystemSnapshot,
        prefer: list[str] | None = None,
        config: ZeroGravityConfig | None = None,
    ) -> List[RemediationPlan]:
        """Inspect issues and generate actionable remediation plans."""
        plans: List[RemediationPlan] = []
        effective_prefer = prefer if prefer is not None else (self.prefer or (config.healing_prefer if config else []))

        for issue in report.issues:
            if issue.category not in (
                IssueCategory.MISSING_BINARY,
                IssueCategory.ENGINE_CONSTRAINT_VIOLATION,
                IssueCategory.VERSION_MISMATCH,
            ):
                continue

            target_version = _resolve_target_version(issue.expected)
            if not target_version:
                continue

            binary = issue.affected_binary or ""
            supported = DEFAULT_PRIORITIES.get(binary, [])
            candidates = _order_managers(supported, effective_prefer)

            for candidate in candidates:
                if _is_manager_available(candidate, snapshot):
                    candidate_plans = _create_plans(candidate, issue, target_version, binary)
                    if candidate_plans:
                        plans.extend(candidate_plans)
                        break

        return plans

    def execute_plan(self, plan: RemediationPlan, snapshot: SystemSnapshot, auto_approve: bool = False) -> bool:
        """Execute a remediation plan, optionally asking for user confirmation."""
        from rich.prompt import Confirm

        if not auto_approve:
            if not Confirm.ask(f"Execute: {' '.join(plan.command)}?"):
                return False

        try:
            if plan.manager_name == "nvm":
                nvm_script = _find_nvm_script(snapshot)
                if nvm_script:
                    nvm_args = " ".join(plan.command[1:])
                    shell_cmd = f'. "{nvm_script}" && nvm {nvm_args}'
                    result = subprocess.run(
                        ["bash", "-c", shell_cmd],
                        check=True,
                        capture_output=True,
                        text=True,
                    )
                elif sys.platform == "win32":
                    result = subprocess.run(
                        ["cmd.exe", "/c"] + plan.command,
                        check=True,
                        capture_output=True,
                        text=True,
                    )
                else:
                    return False
            elif plan.manager_name == "nvm-windows":
                result = subprocess.run(
                    ["cmd.exe", "/c"] + plan.command,
                    check=True,
                    capture_output=True,
                    text=True,
                )
            elif plan.manager_name == "pyenv-win":
                result = subprocess.run(
                    ["cmd.exe", "/c"] + plan.command,
                    check=True,
                    capture_output=True,
                    text=True,
                )
            else:
                result = subprocess.run(
                    plan.command,
                    check=True,
                    capture_output=True,
                    text=True,
                    shell=False,
                )
            return result.returncode == 0
        except subprocess.CalledProcessError:
            return False
