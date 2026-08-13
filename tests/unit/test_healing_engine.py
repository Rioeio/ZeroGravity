from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from zerogravity.healing.engine import HealingEngine, _resolve_target_version
from zerogravity.resolver.models import (
    Issue,
    IssueCategory,
    ResolutionReport,
    Severity,
    SystemSnapshot,
    VersionManagerInfo,
)


@pytest.mark.parametrize(
    "spec,expected",
    [
        ("18.2.0", "18.2.0"),
        ("v18.2.0", "18.2.0"),
        ("^18.2.0", "18"),
        ("~18.2.0", "18.2"),
        ("18.x", "18"),
        (">=18.0.0,<19.0.0", "18"),
        ("18 || 20", "18"),
        ("*", None),
        ("", None),
        (None, None),
    ],
)
def test_resolve_target_version(spec, expected):
    assert _resolve_target_version(spec) == expected


def _node_issue(expected_spec: str = "^18.2.0") -> Issue:
    return Issue(
        severity=Severity.CRITICAL,
        category=IssueCategory.MISSING_BINARY,
        message="Required engine 'node' is not installed.",
        affected_binary="node",
        expected=expected_spec,
    )


def _rust_issue() -> Issue:
    return Issue(
        severity=Severity.CRITICAL,
        category=IssueCategory.MISSING_BINARY,
        message="Required engine 'rust' is not installed.",
        affected_binary="rust",
        expected="1.75.0",
    )


class TestPlanRemediations:
    def test_no_nvm_plan_when_nvm_script_missing(self, tmp_path: Path):
        """nvm reported as detected but nvm.sh isn't on disk -> no plan offered."""
        snapshot = SystemSnapshot(
            version_managers={"nvm": VersionManagerInfo(name="nvm", detected=True, root_path=str(tmp_path))}
        )
        report = ResolutionReport(issues=[_node_issue()])
        plans = HealingEngine().plan_remediations(report, snapshot)
        assert plans == []

    def test_nvm_plan_when_script_present(self, tmp_path: Path):
        (tmp_path / "nvm.sh").write_text("# fake nvm.sh")
        snapshot = SystemSnapshot(
            version_managers={"nvm": VersionManagerInfo(name="nvm", detected=True, root_path=str(tmp_path))}
        )
        report = ResolutionReport(issues=[_node_issue("^18.2.0")])
        plans = HealingEngine().plan_remediations(report, snapshot)
        assert [p.command for p in plans] == [
            ["nvm", "install", "18"],
            ["nvm", "use", "18"],
        ]

    def test_rust_plan_requires_rustup_on_path(self):
        snapshot = SystemSnapshot()
        report = ResolutionReport(issues=[_rust_issue()])
        with patch("shutil.which", return_value=None):
            assert HealingEngine().plan_remediations(report, snapshot) == []
        with patch("shutil.which", return_value="/usr/bin/rustup"):
            plans = HealingEngine().plan_remediations(report, snapshot)
        assert plans[0].command == ["rustup", "override", "set", "1.75.0"]


class TestExecutePlan:
    def test_nvm_runs_via_sourced_shell_not_shell_true_list(self, tmp_path: Path):
        """
        Regression test for the bug where shell=True was combined with a list
        command, silently dropping every argument but the first. Asserts the
        exact argv passed to subprocess.run.
        """
        nvm_script = tmp_path / "nvm.sh"
        nvm_script.write_text("# fake nvm.sh")
        snapshot = SystemSnapshot(
            version_managers={"nvm": VersionManagerInfo(name="nvm", detected=True, root_path=str(tmp_path))}
        )
        plan = HealingEngine().plan_remediations(
            ResolutionReport(issues=[_node_issue("18.2.0")]), snapshot
        )[0]

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            ok = HealingEngine().execute_plan(plan, snapshot, auto_approve=True)

        assert ok is True
        args, kwargs = mock_run.call_args
        assert args[0][0] == "bash"
        assert args[0][1] == "-c"
        assert str(nvm_script) in args[0][2]
        assert "nvm install 18.2.0" in args[0][2]
        assert kwargs.get("shell", False) is False

    def test_nvm_fails_closed_if_script_disappears(self, tmp_path: Path):
        snapshot = SystemSnapshot(
            version_managers={"nvm": VersionManagerInfo(name="nvm", detected=True, root_path=str(tmp_path))}
        )
        plan = HealingEngine().plan_remediations(
            ResolutionReport(issues=[_node_issue("18.2.0")]), snapshot
        )
        assert plan == []  # no script -> nothing planned in the first place

    def test_pyenv_runs_directly_without_shell(self):
        snapshot = SystemSnapshot(
            version_managers={"pyenv": VersionManagerInfo(name="pyenv", detected=True)}
        )
        with patch("shutil.which", return_value="/usr/bin/pyenv"):
            plans = HealingEngine().plan_remediations(
                ResolutionReport(issues=[
                    Issue(
                        severity=Severity.CRITICAL,
                        category=IssueCategory.MISSING_BINARY,
                        message="Required engine 'python' is not installed.",
                        affected_binary="python",
                        expected="3.11.4",
                    )
                ]),
                snapshot,
            )
        assert plans[0].command == ["pyenv", "install", "-s", "3.11.4"]

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            ok = HealingEngine().execute_plan(plans[0], snapshot, auto_approve=True)

        assert ok is True
        args, kwargs = mock_run.call_args
        assert args[0] == ["pyenv", "install", "-s", "3.11.4"]
        assert kwargs.get("shell", False) is False

    def test_declines_without_confirmation(self, tmp_path: Path):
        nvm_script = tmp_path / "nvm.sh"
        nvm_script.write_text("# fake nvm.sh")
        snapshot = SystemSnapshot(
            version_managers={"nvm": VersionManagerInfo(name="nvm", detected=True, root_path=str(tmp_path))}
        )
        plan = HealingEngine().plan_remediations(
            ResolutionReport(issues=[_node_issue("18.2.0")]), snapshot
        )[0]

        with patch("rich.prompt.Confirm.ask", return_value=False), patch("subprocess.run") as mock_run:
            ok = HealingEngine().execute_plan(plan, snapshot, auto_approve=False)

        assert ok is False
        mock_run.assert_not_called()
