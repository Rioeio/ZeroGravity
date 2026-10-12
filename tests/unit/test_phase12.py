from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from zerogravity.config import ZeroGravityConfig
from zerogravity.healing.engine import HealingEngine
from zerogravity.resolver.models import (
    Issue,
    IssueCategory,
    ResolutionReport,
    Severity,
    SystemSnapshot,
    VersionManagerInfo,
)
from zerogravity.scanner.subprocess_utils import run_command
from zerogravity.scanner.version_manager import VERSION_MANAGERS


def _make_issue(binary: str, version: str) -> Issue:
    return Issue(
        severity=Severity.CRITICAL,
        category=IssueCategory.MISSING_BINARY,
        message=f"Missing {binary}",
        affected_binary=binary,
        expected=version,
    )


def test_version_managers_include_modern_toolchains() -> None:
    expected_new = ["uv", "fnm", "volta", "mise", "nvm-windows", "pyenv-win"]
    for m in expected_new:
        assert m in VERSION_MANAGERS, f"{m} missing from VERSION_MANAGERS"
    assert VERSION_MANAGERS["uv"]["list_cmd"] == ["uv", "python", "list", "--only-installed"]


def test_plan_generation_uv() -> None:
    snapshot = SystemSnapshot(
        version_managers={"uv": VersionManagerInfo(name="uv", detected=True)}
    )
    report = ResolutionReport(issues=[_make_issue("python", "3.12.0")])
    plans = HealingEngine().plan_remediations(report, snapshot)
    assert len(plans) == 1
    assert plans[0].manager_name == "uv"
    assert plans[0].command == ["uv", "python", "install", "3.12.0"]


def test_plan_generation_fnm() -> None:
    snapshot = SystemSnapshot(
        version_managers={"fnm": VersionManagerInfo(name="fnm", detected=True)}
    )
    report = ResolutionReport(issues=[_make_issue("node", "20.10.0")])
    plans = HealingEngine().plan_remediations(report, snapshot)
    assert len(plans) == 2
    assert plans[0].manager_name == "fnm"
    assert plans[0].command == ["fnm", "install", "20.10.0"]
    assert plans[1].command == ["fnm", "use", "20.10.0"]


def test_plan_generation_volta() -> None:
    snapshot = SystemSnapshot(
        version_managers={"volta": VersionManagerInfo(name="volta", detected=True)}
    )
    report = ResolutionReport(issues=[_make_issue("node", "^18.0.0")])
    plans = HealingEngine().plan_remediations(report, snapshot)
    assert len(plans) == 1
    assert plans[0].manager_name == "volta"
    assert plans[0].command == ["volta", "install", "node@18"]


def test_plan_generation_mise() -> None:
    snapshot = SystemSnapshot(
        version_managers={"mise": VersionManagerInfo(name="mise", detected=True)}
    )
    report = ResolutionReport(issues=[_make_issue("node", "^20.0.0")])
    plans = HealingEngine().plan_remediations(report, snapshot)
    assert len(plans) == 2
    assert plans[0].manager_name == "mise"
    assert plans[0].command == ["mise", "install", "node@20"]
    assert plans[1].command == ["mise", "use", "node@20"]


def test_healing_priority_and_config_prefer() -> None:
    # Both uv and mise detected for Python; default priority picks uv
    snapshot = SystemSnapshot(
        version_managers={
            "uv": VersionManagerInfo(name="uv", detected=True),
            "mise": VersionManagerInfo(name="mise", detected=True),
        }
    )
    report = ResolutionReport(issues=[_make_issue("python", "3.11.0")])
    plans_default = HealingEngine().plan_remediations(report, snapshot)
    assert plans_default[0].manager_name == "uv"

    # With config prefer = ["mise"], picks mise first
    cfg = ZeroGravityConfig(healing_prefer=["mise"])
    plans_prefer = HealingEngine().plan_remediations(report, snapshot, config=cfg)
    assert plans_prefer[0].manager_name == "mise"


@pytest.mark.skipif(sys.platform != "win32", reason="Windows-only nvm.exe test")
def test_windows_nvm_plan_without_nvm_sh() -> None:
    snapshot = SystemSnapshot(
        version_managers={"nvm-windows": VersionManagerInfo(name="nvm-windows", detected=True)}
    )
    report = ResolutionReport(issues=[_make_issue("node", "^18.0.0")])
    plans = HealingEngine().plan_remediations(report, snapshot)
    assert len(plans) == 2
    assert plans[0].command == ["nvm", "install", "18"]
    assert plans[1].command == ["nvm", "use", "18"]


@pytest.mark.skipif(sys.platform != "win32", reason="Windows-only .cmd/.bat shim test")
async def test_windows_cmd_bat_shim_wrapped_in_cmd_exe(tmp_path: Path) -> None:
    batch_file = tmp_path / "custom_tool.bat"
    batch_file.write_text("@echo off\necho hello_from_bat\n", encoding="utf-8")

    code, out, _ = await run_command([str(batch_file)], timeout=5.0)
    assert code == 0
    assert "hello_from_bat" in out.decode("utf-8")


@pytest.mark.skipif(sys.platform != "win32", reason="Windows-only taskkill process tree test")
async def test_windows_taskkill_kills_process_tree(tmp_path: Path) -> None:
    pid_file = tmp_path / "grandchild.pid"
    script = (
        "import subprocess, sys, time\n"
        "proc = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])\n"
        f"with open(r'{pid_file}', 'w') as f:\n"
        "    f.write(str(proc.pid))\n"
        "time.sleep(30)\n"
    )
    py_file = tmp_path / "spawner.py"
    py_file.write_text(script, encoding="utf-8")

    with pytest.raises(asyncio.TimeoutError):
        await run_command([sys.executable, str(py_file)], timeout=1.0)

    await asyncio.sleep(0.5)
    assert pid_file.exists()
    gc_pid = int(pid_file.read_text().strip())
    res = subprocess.run(["tasklist", "/FI", f"PID eq {gc_pid}"], capture_output=True, text=True)
    assert str(gc_pid) not in res.stdout, f"Grandchild process {gc_pid} still alive"


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX-only process group grandchild test")
async def test_posix_process_group_kills_grandchild(tmp_path: Path) -> None:
    pid_file = tmp_path / "grandchild.pid"
    script = (
        "import subprocess, sys, time\n"
        "proc = subprocess.Popen(['sleep', '30'])\n"
        f"with open('{pid_file}', 'w') as f:\n"
        "    f.write(str(proc.pid))\n"
        "time.sleep(30)\n"
    )
    py_file = tmp_path / "spawner.py"
    py_file.write_text(script, encoding="utf-8")

    with pytest.raises(asyncio.TimeoutError):
        await run_command([sys.executable, str(py_file)], timeout=1.0)

    time.sleep(0.5)
    assert pid_file.exists()
    gc_pid = int(pid_file.read_text().strip())
    with pytest.raises(ProcessLookupError):
        os.kill(gc_pid, 0)
