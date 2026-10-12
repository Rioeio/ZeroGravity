from __future__ import annotations

import asyncio
import logging
import os
import shutil
import signal
import subprocess
import sys
from typing import Any, Sequence, Tuple

logger = logging.getLogger(__name__)


async def _reap(proc: asyncio.subprocess.Process) -> None:
    """Kill a still-running child and its entire process tree, then wait for it."""
    if proc.returncode is None and proc.pid:
        if sys.platform == "win32":
            try:
                subprocess.run(
                    ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=2.0,
                    check=False,
                )
            except (subprocess.SubprocessError, OSError) as err:
                logger.debug("taskkill failed: %s", err)
                try:
                    proc.kill()
                except ProcessLookupError:
                    pass
        else:
            try:
                pgid = os.getpgid(proc.pid)
                os.killpg(pgid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError, OSError) as err:
                logger.debug("os.killpg failed: %s", err)
                try:
                    proc.kill()
                except ProcessLookupError:
                    pass
    elif proc.returncode is None:
        try:
            proc.kill()
        except ProcessLookupError:
            pass

    try:
        await asyncio.wait_for(proc.wait(), timeout=2.0)
    except (asyncio.TimeoutError, OSError) as err:
        logger.debug("Failed reaping process: %s", err, exc_info=True)


async def run_command(cmd: Sequence[str], timeout: float) -> Tuple[int, bytes, bytes]:
    """
    Run a command and return (returncode, stdout, stderr).

    Resolves executables via shutil.which (PATHEXT aware), wraps .cmd/.bat in
    cmd.exe /c on Windows, creates a new session on POSIX for process-tree isolation,
    and terminates the entire process tree on timeout/cancellation.
    """
    if not cmd:
        raise ValueError("Command cannot be empty")

    exec_cmd = list(cmd)
    target = exec_cmd[0]
    resolved = shutil.which(target) or target

    if sys.platform == "win32":
        if target.lower() not in ("cmd", "cmd.exe") and resolved.lower().endswith((".cmd", ".bat")):
            exec_cmd = ["cmd.exe", "/c", resolved] + list(exec_cmd[1:])
        else:
            exec_cmd[0] = resolved
    else:
        exec_cmd[0] = resolved

    kwargs: dict[str, Any] = {
        "stdout": asyncio.subprocess.PIPE,
        "stderr": asyncio.subprocess.PIPE,
    }
    if sys.platform != "win32":
        kwargs["start_new_session"] = True

    proc = await asyncio.create_subprocess_exec(
        *exec_cmd,
        **kwargs,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        return (proc.returncode if proc.returncode is not None else -1), stdout, stderr
    except BaseException:
        await _reap(proc)
        raise
    finally:
        transport = getattr(proc, "_transport", None)
        if transport is not None:
            transport.close()
