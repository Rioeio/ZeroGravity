from __future__ import annotations

import subprocess
from dataclasses import dataclass
from typing import List

from zerogravity.resolver.models import Issue, IssueCategory, ResolutionReport, SystemSnapshot


@dataclass
class RemediationPlan:
    """A planned remediation for a specific issue."""
    issue: Issue
    manager_name: str
    command: List[str]
    description: str


class HealingEngine:
    """Engine responsible for self-healing runtime environment mismatches."""

    def plan_remediations(self, report: ResolutionReport, snapshot: SystemSnapshot) -> List[RemediationPlan]:
        """Inspect issues and generate actionable remediation plans."""
        plans: List[RemediationPlan] = []
        
        for issue in report.issues:
            if issue.category not in (
                IssueCategory.MISSING_BINARY, 
                IssueCategory.ENGINE_CONSTRAINT_VIOLATION, 
                IssueCategory.VERSION_MISMATCH
            ):
                continue
                
            target_version = issue.expected
            if not target_version:
                continue

            # Node issues
            if issue.affected_binary == "node":
                if "nvm" in snapshot.version_managers:
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
                # elif "asdf" in snapshot.version_managers: # ASDF support not fully detailed in requirements
                
            # Python issues
            elif issue.affected_binary == "python":
                if "pyenv" in snapshot.version_managers:
                    plans.append(RemediationPlan(
                        issue=issue,
                        manager_name="pyenv",
                        command=["pyenv", "install", target_version],
                        description=f"Install Python {target_version} via pyenv",
                    ))
                    plans.append(RemediationPlan(
                        issue=issue,
                        manager_name="pyenv",
                        command=["pyenv", "local", target_version],
                        description=f"Set local Python {target_version} via pyenv",
                    ))
                # elif "asdf" in snapshot.version_managers: # ASDF support

            # Rust issues
            elif issue.affected_binary == "rust":
                plans.append(RemediationPlan(
                    issue=issue,
                    manager_name="rustup",
                    command=["rustup", "override", "set", target_version],
                    description=f"Set Rust {target_version} via rustup override",
                ))

        return plans

    def execute_plan(self, plan: RemediationPlan, auto_approve: bool = False) -> bool:
        """Execute a remediation plan, optionally asking for user confirmation."""
        from rich.prompt import Confirm
        
        if not auto_approve:
            if not Confirm.ask(f"Execute: {' '.join(plan.command)}?"):
                return False
                
        try:
            result = subprocess.run(
                plan.command, 
                check=True, 
                capture_output=True, 
                text=True,
                shell=True if plan.manager_name in ("nvm", "pyenv") else False
            )
            return result.returncode == 0
        except subprocess.CalledProcessError:
            return False
        except FileNotFoundError:
            return False
