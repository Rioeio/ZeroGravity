from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

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


def _resolve_target_version(spec: str) -> Optional[str]:
    """
    Best-effort extraction of a version nvm/pyenv/rustup can actually install
    from a raw constraint string ("^18.2.0", ">=18.0.0,<19.0.0", "18.x", "3.11").

    Exact pins resolve directly. Ranges resolve to the leading major (or
    major.minor for '~' ranges), which nvm/pyenv/rustup expand to the latest
    matching release themselves. Not a full semver/PEP440 resolver -- if no
    version-like token can be found at all, returns None so the caller skips
    planning a remediation it can't actually carry out.
    """
    if not spec:
        return None

    spec = spec.strip()
    exact = _EXACT_VERSION_RE.match(spec)
    if exact:
        return exact.group(1)

    # Multiple alternatives ("18 || 20") or a compound range
    # (">=18.0.0,<19.0.0") -- take the first component as the target.
    first_component = re.split(r"\|\||,", spec)[0].strip()

    match = _LEADING_VERSION_RE.search(first_component)
    if not match:
        return None

    major, minor = match.group(1), match.group(2)
    if first_component.startswith("~") and minor:
        return f"{major}.{minor}"
    return major


def _find_nvm_script(snapshot: SystemSnapshot) -> Optional[Path]:
    """
    nvm is a shell function sourced from nvm.sh, not a binary on PATH, so it
    can't be exec'd directly. Locate the script from the NVM_DIR the scanner
    already recorded on the snapshot.
    """
    nvm_info = snapshot.version_managers.get("nvm")
    if not nvm_info or not nvm_info.root_path:
        return None
    script = Path(nvm_info.root_path) / "nvm.sh"
    return script if script.is_file() else None


class HealingEngine:
    """Engine responsible for self-healing runtime environment mismatches."""

    def plan_remediations(self, report: ResolutionReport, snapshot: SystemSnapshot) -> List[RemediationPlan]:
        """Inspect issues and generate actionable remediation plans.

        Only plans a remediation when the manager needed to carry it out is
        actually invocable on this machine -- an unusable plan is worse than
        no plan, since execute_plan would silently no-op on it.
        """
        plans: List[RemediationPlan] = []

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

            if issue.affected_binary == "node":
                if _find_nvm_script(snapshot):
                    plans.append(RemediationPlan(
                        issue=issue,
                        manager_name="nvm",
                        command=["nvm", "install", target_version],
                        description=f"Install Node.js {target_version} via nvm",
                    ))
                    plans.append(RemediationPlan(
                        issue=issue,
                        manager_name="nvm",
                        command=["nvm", "use", target_version],
                        description=f"Use Node.js {target_version} via nvm",
                    ))

            elif issue.affected_binary == "python":
                if "pyenv" in snapshot.version_managers and shutil.which("pyenv"):
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

            elif issue.affected_binary == "rust":
                if shutil.which("rustup"):
                    plans.append(RemediationPlan(
                        issue=issue,
                        manager_name="rustup",
                        command=["rustup", "override", "set", target_version],
                        description=f"Set Rust {target_version} via rustup override",
                    ))

        return plans

    def execute_plan(self, plan: RemediationPlan, snapshot: SystemSnapshot, auto_approve: bool = False) -> bool:
        """Execute a remediation plan, optionally asking for user confirmation.

        nvm is invoked by sourcing nvm.sh in a real bash process and calling
        the shell function inside it -- it has no standalone binary, so it
        can never be run with shell=False, and running it with shell=True on
        a list silently drops every argument but the first. Every other
        manager is a real executable and runs directly with shell=False.
        """
        from rich.prompt import Confirm

        if not auto_approve:
            if not Confirm.ask(f"Execute: {' '.join(plan.command)}?"):
                return False

        try:
            if plan.manager_name == "nvm":
                nvm_script = _find_nvm_script(snapshot)
                if not nvm_script:
                    return False
                nvm_args = " ".join(plan.command[1:])
                shell_cmd = f'. "{nvm_script}" && nvm {nvm_args}'
                result = subprocess.run(
                    ["bash", "-c", shell_cmd],
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
