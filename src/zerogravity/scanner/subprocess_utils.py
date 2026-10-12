from __future__ import annotations

import asyncio
import logging
from typing import Sequence, Tuple

logger = logging.getLogger(__name__)


async def _reap(proc: asyncio.subprocess.Process) -> None:
    """Kill a still-running child and wait for it so nothing is orphaned."""
    if proc.returncode is None:
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

    On timeout, cancellation, or any error the child is killed and reaped, and
    its transport is closed before returning, so no transport outlives the
    event loop and triggers __del__ warnings at interpreter shutdown.
    """
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        return (proc.returncode if proc.returncode is not None else -1), stdout, stderr
    except BaseException:
        await _reap(proc)
        raise
    finally:
        # asyncio exposes no public close() for a Process; close() on the private
        # transport is idempotent and is the standard workaround for this leak.
        transport = getattr(proc, "_transport", None)
        if transport is not None:
            transport.close()
